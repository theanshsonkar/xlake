import gzip
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from pipeline import find_programmes as fp


def row(url, org="Acme", cat="fellowship"):
    return {"record_type": "programme", "category": cat, "official_url": url, "organizer": org,
            "is_live": True, "programme_status": "open"}


class PathFilterTests(unittest.TestCase):
    def test_keeps_and_drops(self):
        self.assertEqual(fp.classify_path("https://a.org/programs/summer-research-fellowship"), "")
        self.assertIsNone(fp.classify_path("https://a.org/news/2026/fellowship-winners"))
        self.assertIsNone(fp.classify_path("https://a.org/people/x"))
        self.assertIsNone(fp.classify_path("https://a.org/"))
        self.assertIsNone(fp.classify_path("https://a.org/fellowship/handbook.pdf"))
        self.assertIsNone(fp.classify_path("https://a.org/hackathon-fellowship"))
        self.assertEqual(fp.classify_path("https://a.org/x/fellowship-scholarship"), "")

    def test_name(self):
        self.assertEqual(fp.provisional_name("https://a.org/programs/summer-research-fellowship/apply"),
                         "Summer Research Fellowship")


class SitemapTests(unittest.TestCase):
    def setUp(self):
        self.budget = fp.Budget(100, sleep=lambda s: None)

    def test_robots_disallow(self):
        urls, blocked = fp.sitemap_urls("a.org", self.budget, lambda u: b"", lambda u: False)
        self.assertEqual((urls, blocked), ([], True))

    def test_index_gzip(self):
        index = b"<sitemapindex><sitemap><loc>https://a.org/s1.xml.gz</loc></sitemap></sitemapindex>"
        leaf = gzip.compress(b"<urlset><url><loc>https://a.org/fellowship/x</loc></url></urlset>")
        files = {"https://a.org/robots.txt": b"User-agent: *\nSitemap: https://a.org/index.xml\n",
                 "https://a.org/index.xml": index, "https://a.org/s1.xml.gz": leaf}
        urls, blocked = fp.sitemap_urls("a.org", self.budget, lambda u: files[u], lambda u: True)
        self.assertEqual(urls, ["https://a.org/fellowship/x"])
        self.assertFalse(blocked)

    def test_disallowed_candidate_dropped(self):
        urls = {"https://a.org/fellowship/x": "finder:sitemap", "https://a.org/private/fellowship/y": "finder:sitemap"}
        ok = {u: s for u, s in urls.items() if "private" not in u}
        got = fp.candidates_for_host("a.org", ok, "fellowships", "Acme", set(), 10)
        self.assertEqual([g[1] for g in got], ["https://a.org/fellowship/x"])


class RunTests(unittest.TestCase):
    def _setup(self, td):
        shards = os.path.join(td, "shards")
        os.makedirs(shards, exist_ok=True)
        json.dump([row("https://a.org/fellowship/known")], open(os.path.join(shards, "fellowships.json"), "w"))
        return shards, os.path.join(td, "seeds")

    def _run(self, td, dry=False):
        shards, seeds = self._setup(td)
        sm = (b"<urlset><url><loc>https://a.org/fellowship/known/</loc></url>"
              b"<url><loc>https://a.org/fellowship/new-one</loc></url>"
              b"<url><loc>https://a.org/news/fellowship-news</loc></url></urlset>")
        files = {"https://a.org/robots.txt": b"", "https://a.org/sitemap.xml": sm}
        out = []
        res = fp.run(shards, ["fellowships"], seeds_dir=seeds, use_cc=False, dry_run=dry,
                     get=lambda u: files[u], allowed=lambda u: True, sleep=lambda s: None, out=out.append)
        return res, seeds, out

    def test_dedupe_and_append_only(self):
        with tempfile.TemporaryDirectory() as td:
            res, seeds, out = self._run(td, dry=True)
            self.assertEqual([s["official_url"] for s in res["fellowships"]], ["https://a.org/fellowship/new-one"])
            self.assertFalse(os.path.exists(os.path.join(seeds, "finder_fellowships.json")))
            self.assertIn("new=1", out[0])
            self._run(td)
            path = os.path.join(seeds, "finder_fellowships.json")
            data = json.load(open(path))
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["discovered_from"], "finder:sitemap")
            self.assertEqual(data[0]["source_kind"], "official")
            self.assertEqual(data[0]["organizer"], "Acme")
            data.append({"source_id": "keep", "official_url": "https://z.org/fellowship/z"})
            json.dump(data, open(path, "w"))
            self._run(td)  # nothing new; existing entries survive
            self.assertEqual(len(json.load(open(path))), 2)

    def test_loader_includes_finder_seeds(self):
        from categories.programme_core import load_generated_seeds
        with tempfile.TemporaryDirectory() as td:
            seed = fp.make_seed("fellowships", "https://a.org/fellowship/new-one", "Acme", "finder:sitemap", "now")
            json.dump([seed], open(os.path.join(td, "finder_fellowships.json"), "w"))
            with patch.dict(os.environ, {"XLAKE_GENERATED_SEEDS_DIR": td}):
                got = load_generated_seeds("fellowships")
            self.assertEqual([s["official_url"] for s in got], ["https://a.org/fellowship/new-one"])


if __name__ == "__main__":
    unittest.main()


class PageCheckTests(unittest.TestCase):
    def test_url_rejects(self):
        for u in ("https://a.org/product-page/fellowship-shirt", "https://a.org/blog/fellowship-x",
                  "https://a.org/fellows/jane-fellowship", "https://a.org/fellowship/meet-the-fellows",
                  "https://a.org/grants/handbook", "https://a.org/terms/grant-terms",
                  "https://grafana.com/grafana/dashboards/grant"):
            self.assertIsNone(fp.classify_path(u), u)

    def test_language_dedupe(self):
        urls = {u: "s" for u in ("https://a.org/de/fellowship/x", "https://a.org/fellowship/x",
                                 "https://a.org/es/scholarship/y", "https://a.org/ja/scholarship/y")}
        got = [c[1] for c in fp.candidates_for_host("a.org", urls, "fellowships", "A", set(), 10)]
        self.assertEqual(sorted(got), ["https://a.org/es/scholarship/y", "https://a.org/fellowship/x"])

    def test_bigfuture_generic(self):
        self.assertTrue(fp.is_generic_host("bigfuture.collegeboard.org"))

    def test_page_check(self):
        ok = "<title>Acme Fellowship</title><body>How to apply: deadline May 1</body>"
        self.assertEqual(fp.page_check(ok), ("Acme Fellowship", ""))
        self.assertEqual(fp.page_check("<title>Acme Fellowship winners</title>apply")[1], "past_or_news")
        self.assertEqual(fp.page_check("<title>About us</title>apply")[1], "title_no_category")
        self.assertEqual(fp.page_check("<title>Acme Fellowship</title>hello")[1], "no_applicant_cue")

    def test_run_with_fake_fetch(self):
        with tempfile.TemporaryDirectory() as td:
            shards = os.path.join(td, "shards")
            os.makedirs(shards)
            json.dump([row("https://a.org/fellowship/known")], open(os.path.join(shards, "fellowships.json"), "w"))
            sm = (b"<urlset><url><loc>https://a.org/fellowship/good</loc></url>"
                  b"<url><loc>https://a.org/fellowship/bad</loc></url></urlset>")
            files = {"https://a.org/robots.txt": b"", "https://a.org/sitemap.xml": sm}
            pages = {"https://a.org/fellowship/good": "<title>Good Fellowship | Acme</title>Apply by June",
                     "https://a.org/fellowship/bad": "<title>Shop</title>apply"}
            out = []
            res = fp.run(shards, ["fellowships"], seeds_dir=os.path.join(td, "s"), use_cc=False, dry_run=True,
                         get=lambda u: files[u], allowed=lambda u: True, sleep=lambda s: None, out=out.append,
                         fetch=lambda u: (pages[u], u))
            self.assertEqual([s["official_url"] for s in res["fellowships"]], ["https://a.org/fellowship/good"])
            self.assertIn("title_no_category", out[0])
