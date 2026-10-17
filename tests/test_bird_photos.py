"""Photo enrichment is optional, attributed, cached and safe to render."""
import io

from PIL import Image

from birdframe.bird_photos import enrich_species


class Response:
    def __init__(self, data=None, content=b''):
        self.data, self.content = data, content

    def json(self):
        return self.data

    def raise_for_status(self):
        pass


def test_photo_cache_retains_credits_and_never_repeats_network_work(tmp_path):
    image = io.BytesIO()
    Image.new('RGB', (40, 30), 'brown').save(image, 'JPEG')
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        if 'en.wikipedia.org' in url:
            return Response({'query': {'pages': {'1': {'title': 'European robin',
                'pageimage': 'Robin.jpg', 'extract': 'A small bird.'}}}})
        if 'commons.wikimedia.org' in url:
            return Response({'query': {'pages': {'2': {'imageinfo': [{
                'thumburl': 'https://upload.wikimedia.org/robin.jpg',
                'descriptionurl': 'https://commons.wikimedia.org/wiki/File:Robin.jpg',
                'extmetadata': {'Artist': {'value': '<a href="//example.org">Robin Photographer</a>'},
                                'LicenseShortName': {'value': 'CC BY-SA 4.0'},
                                'LicenseUrl': {'value': 'https://creativecommons.org/licenses/by-sa/4.0/'}}}]}}}})
        return Response(content=image.getvalue())

    species = [{'scientific': 'Erithacus rubecula', 'count': 10}]
    cache, out = tmp_path / 'cache', tmp_path / 'site'
    enrich_species(species, cache, out, http_get=get, now=100000)
    photo = species[0]['photo']
    assert photo['author'] == 'Robin Photographer'
    assert photo['license'] == 'CC BY-SA 4.0'
    assert photo['intro'] == 'A small bird.'
    assert (out / photo['url']).is_file()
    enrich_species(species, cache, out, http_get=get, now=200000)
    assert len(calls) == 3
    enrich_species([], cache, out, http_get=get)
    assert list((out / 'birds').glob('*')) == []


def test_failed_photos_are_bounded_and_back_off(tmp_path):
    calls = []

    def unavailable(*args, **kwargs):
        calls.append(1)
        raise OSError('offline')

    species = [{'scientific': str(i), 'count': i} for i in range(5)]
    cache, out = tmp_path / 'cache', tmp_path / 'out'
    enrich_species(species, cache, out, http_get=unavailable, now=100000, max_fetch=2)
    assert len(calls) == 2
    enrich_species(species, cache, out, http_get=unavailable, now=100001, max_fetch=0)
    assert len(calls) == 2 and not any('photo' in bird for bird in species)
