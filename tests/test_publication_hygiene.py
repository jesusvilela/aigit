from pathlib import Path

from aigit.core import iter_repo_files, parse_markdown, scout_repo


def test_semantic_index_excludes_package_build_outputs(tmp_path: Path) -> None:
    (tmp_path / 'src.py').write_text('def ready():\n    return True\n', encoding='utf-8')
    (tmp_path / 'build').mkdir()
    (tmp_path / 'build' / 'generated.py').write_text('x = 1\n', encoding='utf-8')
    (tmp_path / 'dist').mkdir()
    (tmp_path / 'dist' / 'package.whl').write_bytes(b'wheel')
    (tmp_path / 'brand.png').write_bytes(b'not source')

    assert iter_repo_files(tmp_path) == [Path('src.py')]


def test_scout_excludes_generated_runtime_and_semantic_state(tmp_path: Path) -> None:
    (tmp_path / 'src.py').write_text('x = 1\n', encoding='utf-8')
    for directory in ('.semantic', '.aigit', '.deerflow', 'build', 'dist'):
        target = tmp_path / directory
        target.mkdir()
        (target / 'generated.txt').write_text('not source\n', encoding='utf-8')

    summary = scout_repo(tmp_path)

    assert summary.file_count == 1
    assert summary.total_bytes == len('x = 1\n')


def test_markdown_parser_ignores_hash_comments_inside_fenced_code() -> None:
    chunks = parse_markdown(
        'README.md',
        '# Overview\n\n```bash\n# This is a shell comment\necho ready\n```\n\n## Next\n',
    )

    assert [chunk.anchor for chunk in chunks] == ['Overview', 'Next']
