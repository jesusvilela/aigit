"""Pluggable code-writing backends for the crew simulation.

Three backends behind one interface, selected by environment so the same
scenario runs in CI and against real models:

* ``DeterministicBackend`` -- the default. No network, no weights, fixed
  outputs, so CI can assert on the result.
* ``OpenAICompatBackend`` -- any OpenAI-compatible chat API (OpenAI, Moonshot,
  vLLM, ollama, llama-server).
* ``TransformersBackend`` -- local weights via transformers.

Selection (first match wins):

    AIGIT_CREW_ENDPOINT=https://api.openai.com/v1  AIGIT_CREW_MODEL=gpt-4o-mini
    AIGIT_CREW_LOCAL=1                             AIGIT_CREW_MODEL=LiquidAI/LFM2-1.2B
    (nothing set)                                  -> deterministic
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

__all__ = [
    'DeterministicBackend',
    'OpenAICompatBackend',
    'TransformersBackend',
    'build_prompt',
    'extract_code',
    'select_backend',
]


def build_prompt(task: dict, variant: str) -> str:
    """Ask for exactly one top-level function.

    Small models drift into classes and imports without this framing, and a
    stray class changes the chunk anchor -- which silently changes what the
    merge gate is comparing.
    """
    return (
        'You are a senior Python engineer on a distributed team.\n'
        'Output EXACTLY ONE top-level function and nothing else: no classes, '
        'no imports, no comments, no examples, no prose.\n'
        f"def {task['func']}({task['params']}):\n"
        f"Behaviour: {task['spec']}\n"
        f'Team style hint ({variant}): let this influence the implementation.\n'
        'Return only a ```python code block containing just that function.'
    )


def extract_code(text: str) -> str:
    """Recover a function body from a model reply.

    Deliberately does *not* rescue prose: a refusal or an explanation must stay
    unparseable so the strict chunk gate rejects it instead of committing it.
    """
    fenced = re.search(r'```(?:python)?\s*\n(.*?)```', text, re.DOTALL)
    if fenced:
        return fenced.group(1).strip() + '\n'
    bare = re.search(r'(^def \w+\(.*)', text, re.DOTALL | re.MULTILINE)
    if bare:
        return bare.group(1).strip() + '\n'
    return text.strip() + '\n'


class DeterministicBackend:
    """Fixed outputs standing in for a model, so CI can assert on the result.

    The variants are chosen to reproduce the collisions a real crew produces:
    two agents given different style hints write the same function differently
    (``add/add``), and one writes it under a different name entirely
    (``duplicate-work``).
    """

    name = 'deterministic'
    real = False

    #: variant -> body, keyed by the function being written
    _IMPLS: dict[str, dict[str, str]] = {
        'route': {
            'default': (
                "    handler = registry_lookup(request['intent'])\n"
                '    if handler is None:\n'
                "        raise KeyError(request['intent'])\n"
                '    return handler(request)\n'
            ),
        },
        'allow_request': {
            'default': (
                "    bucket['tokens'] = min(bucket['capacity'], bucket['tokens'] + bucket['refill'])\n"
                "    if bucket['tokens'] < cost:\n"
                '        return False\n'
                "    bucket['tokens'] -= cost\n"
                '    return True\n'
            ),
            'broken': "    return bucket['tokens'] >=\n",  # unparseable on purpose
        },
        'register_tool': {
            'default': (
                '    if name in _TOOLS:\n'
                "        raise ValueError(f'duplicate tool {name}')\n"
                '    _TOOLS[name] = handler\n'
                '    return handler\n'
            ),
        },
        'pick_provider': {
            # two agents, one ticket, same name -> add/add
            'cost_first': (
                '    for provider in sorted(_PROVIDERS, key=lambda p: p["cost"]):\n'
                "        if model in provider['models']:\n"
                "            return provider['name']\n"
                "    return 'fallback'\n"
            ),
            'latency_first': (
                '    for provider in sorted(_PROVIDERS, key=lambda p: p["latency_ms"]):\n'
                "        if model in provider['models']:\n"
                "            return provider['name']\n"
                "    return 'fallback'\n"
            ),
            # a third agent solves the same ticket under a different NAME,
            # which add/add cannot see -> duplicate-work
            'renamed': (
                '    for provider in sorted(_PROVIDERS, key=lambda p: p["cost"]):\n'
                "        if model in provider['models']:\n"
                "            return provider['name']\n"
                "    return 'fallback'\n"
            ),
        },
    }

    def write_function(self, task: dict, variant: str) -> str:
        # An agent may publish the same work under its own name, so the body is
        # keyed on the ticket rather than on the identifier it chose.
        impls = self._IMPLS[task.get('impl_key', task['func'])]
        body = impls.get(variant) or next(iter(impls.values()))
        return f"def {task['func']}({task['params']}):\n{body}"


class OpenAICompatBackend:
    """Any OpenAI-compatible chat API. ``base_url`` must include the API root."""

    real = True

    def __init__(self, base_url: str, model: str, api_key: str | None = None):
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.api_key = api_key
        self.name = f'openai-compat:{model}'

    def complete(self, prompt: str, max_tokens: int = 220) -> str:
        payload = json.dumps(
            {
                'model': self.model,
                'messages': [{'role': 'user', 'content': prompt}],
                'temperature': 0.3,
                'max_tokens': max_tokens,
            }
        ).encode()
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        request = urllib.request.Request(self.base_url + '/chat/completions', payload, headers)
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read())
        return data['choices'][0]['message']['content']

    def write_function(self, task: dict, variant: str) -> str:
        return extract_code(self.complete(build_prompt(task, variant)))


class TransformersBackend:
    """Local weights. Loads lazily so importing this module stays cheap."""

    real = True

    def __init__(self, model_id: str, dtype: str | None = None):
        import torch
        from transformers import AutoTokenizer

        self.torch = torch
        resolved = {
            'float32': torch.float32,
            'bfloat16': torch.bfloat16,
            'float16': torch.float16,
        }[dtype or os.environ.get('AIGIT_CREW_DTYPE', 'float32')]
        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        try:
            from transformers import AutoModelForCausalLM

            self.model = AutoModelForCausalLM.from_pretrained(
                model_id, dtype=resolved, low_cpu_mem_usage=True
            )
        except (ValueError, KeyError, OSError):
            # multimodal checkpoints (e.g. Gemma 3 4B) expose a different class
            from transformers import AutoModelForImageTextToText

            self.model = AutoModelForImageTextToText.from_pretrained(
                model_id, dtype=resolved, low_cpu_mem_usage=True
            )
        self.model.eval()
        self.name = f'transformers:{model_id}'

    def complete(self, prompt: str, max_tokens: int = 220) -> str:
        encoded = self.tokenizer.apply_chat_template(
            [{'role': 'user', 'content': prompt}],
            add_generation_prompt=True,
            return_tensors='pt',
            return_dict=True,
        )
        prompt_len = encoded['input_ids'].shape[-1]
        kwargs: dict = {
            'max_new_tokens': max_tokens,
            'pad_token_id': self.tokenizer.eos_token_id,
        }
        if os.environ.get('AIGIT_CREW_SAMPLE') == '1':
            kwargs.update(
                do_sample=True,
                temperature=float(os.environ.get('AIGIT_CREW_TEMP', '0.8')),
                top_p=0.95,
            )
        else:
            kwargs['do_sample'] = False
        with self.torch.no_grad():
            output = self.model.generate(**encoded, **kwargs)
        return self.tokenizer.decode(output[0][prompt_len:], skip_special_tokens=True)

    def write_function(self, task: dict, variant: str) -> str:
        return extract_code(self.complete(build_prompt(task, variant)))


def select_backend() -> tuple[object, str]:
    """Pick a backend from the environment. Falls back to deterministic."""
    model = os.environ.get('AIGIT_CREW_MODEL', '')
    endpoint = os.environ.get('AIGIT_CREW_ENDPOINT')
    if endpoint and model:
        base = endpoint if endpoint.rstrip('/').endswith('/v1') else endpoint.rstrip('/') + '/v1'
        backend = OpenAICompatBackend(base, model, os.environ.get('AIGIT_CREW_API_KEY'))
        return backend, f'real model over {endpoint}'
    if os.environ.get('AIGIT_CREW_LOCAL') == '1' and model:
        try:
            backend = TransformersBackend(model)
            return backend, 'real model from local weights'
        except Exception as exc:  # torch/transformers missing or weights absent
            return DeterministicBackend(), f'deterministic (local load failed: {type(exc).__name__})'
    return DeterministicBackend(), 'deterministic (set AIGIT_CREW_ENDPOINT or AIGIT_CREW_LOCAL for a real model)'
