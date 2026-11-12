# Xlake engine

The data collector behind [xlake.site](https://xlake.site). It reads opportunities (internships, jobs,
fellowships, scholarships, grants, research, hackathons, open source, startup and community programmes)
from official sources, keeps proof and freshness, and links to the original application page.
It never submits applications and never accesses LinkedIn or Naukri.

Python 3.12, standard library only.

```bash
cd engine
python3 -m unittest discover -s tests       # offline tests
python3 -m pipeline.read_url URL            # inspect one URL (network)
python3 -m pipeline.build_fixtures check    # offline fixture check
```

Full sweeps run on GitHub Actions (`.github/workflows/`).
