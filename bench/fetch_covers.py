"""
Downloads public domain artwork (CC0, The Metropolitan Museum of Art Open Access) to stand in for album
covers in the color study. Pictures go to data/covers/ (not in git), and the list of what was used,
with links, goes to results/covers_manifest.json so the study can be rebuilt.

    python bench/fetch_covers.py
"""
import os, io, json, time, urllib.request, urllib.parse

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "data", "covers")
API = "https://collectionapi.metmuseum.org/public/collection"
# a spread of subjects so the colors cover dark, light, saturated and nearly grey pictures
TERMS = ["abstract", "night", "sunset", "sea", "flowers", "portrait", "poster", "woodblock print", "textile",
         "photograph", "snow", "fire", "gold", "blue", "red", "green", "black", "white", "jazz", "dance"]
PER_TERM = 8


def get(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "aura-color-study"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def main():
    os.makedirs(OUT, exist_ok=True)
    manifest, seen = [], set()
    for term in TERMS:
        q = urllib.parse.urlencode({"q": term, "hasImages": "true", "isPublicDomain": "true", "limit": 40, "offset": 0})
        ids = json.loads(get(f"{API}/v1.1/search?{q}")).get("objectIDs") or []
        got = 0
        for oid in ids:
            if got >= PER_TERM or oid in seen:
                continue
            try:
                obj = json.loads(get(f"{API}/v1/objects/{oid}"))
                url = obj.get("primaryImageSmall")
                if not obj.get("isPublicDomain") or not url:
                    continue
                im = Image.open(io.BytesIO(get(url))).convert("RGB")
            except Exception:
                continue
            s = min(im.size)
            im = im.crop(((im.width - s) // 2, (im.height - s) // 2, (im.width - s) // 2 + s, (im.height - s) // 2 + s))
            im = im.resize((400, 400), Image.Resampling.LANCZOS)
            name = f"met_{oid}.jpg"
            im.save(os.path.join(OUT, name), quality=92)
            seen.add(oid)
            got += 1
            manifest.append({"file": name, "met_object_id": oid, "title": obj.get("title"),
                             "artist": obj.get("artistDisplayName"), "date": obj.get("objectDate"),
                             "search_term": term, "image_url": url, "object_url": obj.get("objectURL"),
                             "license": "CC0 (Met Open Access, public domain)"})
            time.sleep(0.2)
        print(term, got, flush=True)
    with open(os.path.join(ROOT, "results", "covers_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(len(manifest), "pictures")


if __name__ == "__main__":
    main()
