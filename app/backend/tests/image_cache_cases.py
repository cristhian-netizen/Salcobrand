"""Fast images: cookie-only auth for image URLs (no per-tab query), ETag + private max-age + 304, and lazy
disk-cached thumbnails (?w=). Authorization still runs on this server for every request that reaches it."""
import io
import shutil


class ImageCacheCases:
    def tab_only_client(self, username, selector):
        """A browser tab that logged in with a selector: only the per-tab cookie, no legacy cookie."""
        client = self.client(None)
        self.tab_login(client, username, selector)
        return client

    def test_images_accept_cookie_only_auth_and_keep_scope(self):
        own = self.client('replenisher')
        response = own.get('/uploads/point-a/own.jpg')  # no portal_session: the cookie authenticates
        self.assertEqual(response.status_code, 200)
        self.assertIn('private', response.headers['cache-control'])
        self.assertIn('immutable', response.headers['cache-control'])
        # A tab that logged in with a selector never sent the legacy cookie: its image URLs work without the query.
        analyst_tab = self.tab_only_client('analyst', 'd' * 32)
        self.assertEqual(analyst_tab.get('/uploads/point-a/other.jpg').status_code, 200)
        self.assertEqual(analyst_tab.get(f"/api/readings/{self.other['id']}/crops/0/0.jpg").status_code, 200)
        self.assertEqual(analyst_tab.get('/uploads/point-c/foreign.jpg').status_code, 403)  # scope still enforced
        replenisher_tab = self.tab_only_client('replenisher', 'e' * 32)
        self.assertEqual(replenisher_tab.get('/uploads/point-a/other.jpg').status_code, 403)
        self.assertEqual(replenisher_tab.get(f"/api/readings/{self.other['id']}/crops/0/0.jpg").status_code, 403)
        # An explicit selector keeps its strict per-tab meaning (backward compatible URLs).
        self.assertEqual(own.get('/uploads/point-a/own.jpg?portal_session=' + 'f' * 32).status_code, 401)
        self.assertEqual(self.client(None).get('/uploads/point-a/own.jpg').status_code, 401)

    def test_images_answer_304_on_matching_etag(self):
        own = self.client('replenisher')
        for path in ('/uploads/point-a/own.jpg', f"/api/readings/{self.own['id']}/crops/0/0.jpg"):
            first = own.get(path)
            self.assertEqual(first.status_code, 200, path)
            etag = first.headers['etag']
            self.assertTrue(etag.startswith('"') and etag.endswith('"'))
            again = own.get(path, headers={'If-None-Match': etag})
            self.assertEqual(again.status_code, 304, path)
            self.assertEqual(again.content, b'')
            self.assertEqual(again.headers['etag'], etag)
            self.assertIn('max-age', again.headers['cache-control'])
            changed = own.get(path, headers={'If-None-Match': '"otra-version"'})
            self.assertEqual(changed.status_code, 200, path)

    def big_jpeg(self, size=1200, color='white'):
        from PIL import Image
        buffer = io.BytesIO()
        Image.new('RGB', (size, size), color).save(buffer, 'JPEG', quality=90)
        return buffer.getvalue()

    def test_thumbnails_are_downscaled_cached_on_disk_and_never_reencoded(self):
        from PIL import Image
        thumbs = self.db.DATA_DIR / 'thumbs'
        shutil.rmtree(thumbs, ignore_errors=True)
        self.addCleanup(shutil.rmtree, thumbs, ignore_errors=True)
        self.storage.get.return_value = self.big_jpeg()
        self.addCleanup(lambda: setattr(self.storage.get, 'return_value', b'synthetic-photo'))
        self.addCleanup(lambda: setattr(self.core.crop_jpeg, 'return_value', b'synthetic-crop'))
        self.addCleanup(self.main._crop_cached.cache_clear)
        own = self.client('replenisher')
        first = own.get('/uploads/point-a/own.jpg?w=256')
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.headers['content-type'], 'image/jpeg')
        with Image.open(io.BytesIO(first.content)) as thumb:
            self.assertLessEqual(max(thumb.size), 256)
        cached = list((thumbs / 'uploads').glob('*-w256.jpg'))
        self.assertEqual(len(cached), 1)
        # The second request reads the cached file: replacing it on disk changes the answer, no re-encode happens.
        marker = b'\xff\xd8\xffmarker-from-disk-cache'
        cached[0].write_bytes(marker)
        second = own.get('/uploads/point-a/own.jpg?w=200')  # 200 falls in the same 256 bucket
        self.assertEqual(second.content, marker)
        self.assertEqual(len(list((thumbs / 'uploads').glob('*.jpg'))), 1)
        # The full-size URL keeps serving the original bytes.
        full = own.get('/uploads/point-a/own.jpg')
        self.assertEqual(full.content, self.storage.get.return_value)
        # Thumbnails revalidate like any image.
        etag = second.headers['etag']
        self.assertEqual(own.get('/uploads/point-a/own.jpg?w=256', headers={'If-None-Match': etag}).status_code, 304)
        # Crops get their own cached variants.
        self.core.crop_jpeg.return_value = self.big_jpeg(900, 'gray')
        crop = own.get(f"/api/readings/{self.own['id']}/crops/0/0.jpg?w=128")
        self.assertEqual(crop.status_code, 200)
        with Image.open(io.BytesIO(crop.content)) as thumb:
            self.assertLessEqual(max(thumb.size), 128)
        self.assertEqual(len(list((thumbs / 'crops').glob('*-w128.jpg'))), 1)

    def test_thumbnail_of_undecodable_bytes_falls_back_to_the_original(self):
        thumbs = self.db.DATA_DIR / 'thumbs'
        shutil.rmtree(thumbs, ignore_errors=True)
        self.addCleanup(shutil.rmtree, thumbs, ignore_errors=True)
        own = self.client('replenisher')
        response = own.get('/uploads/point-a/own.jpg?w=256')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'synthetic-photo')  # QA bytes are not an image: served untouched
        self.assertFalse((thumbs / 'uploads').exists())
