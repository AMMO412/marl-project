"""离线示意页的打包与原实验目录保护。画面行为由浏览器检查验证。"""
import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from generate_task_schematics import generate


class SchematicExportTests(unittest.TestCase):
    def make_images(self, folder):
        folder.mkdir()
        pixel = base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aMZkAAAAASUVORK5CYII=')
        for i in range(1, 7):
            (folder / ('image-%d.png' % i)).write_bytes(pixel)

    def test_export_embeds_all_references_and_marks_schematic(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_images(root / 'refs')
            page = generate(root / 'refs', root / 'out')
            content = page.read_text(encoding='utf-8')
            manifest = json.loads((page.parent / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(content.count('data:image/png;base64,'), 6)
            self.assertNotIn('__REFERENCE_IMAGES__', content)
            self.assertEqual(len(manifest['modes']), 5)
            self.assertFalse(manifest['execution_or_simulation_result'])

    def test_existing_experiment_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_images(root / 'refs')
            out = root / 'experiment'
            out.mkdir()
            previous = b'{"backend":"mock_only"}'
            (out / 'manifest.json').write_bytes(previous)
            with self.assertRaises(ValueError):
                generate(root / 'refs', out)
            self.assertEqual((out / 'manifest.json').read_bytes(), previous)
            self.assertFalse((out / 'index.html').exists())

    def test_only_a_marked_schematic_directory_can_be_regenerated(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_images(root / 'refs')
            first = generate(root / 'refs', root / 'out')
            original = first.read_bytes()
            second = generate(root / 'refs', root / 'out')
            self.assertEqual(second.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
