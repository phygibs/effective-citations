# Effective Citations

[Open the live calculator](https://phygibs.github.io/effective-citations/)

A browser calculator for physics papers in the INSPIRE-HEP snapshot. Enter a title or an INSPIRE record ID to compare direct citations with effective citations at 0.5% or 1%. The page searches the live INSPIRE catalog and reads precomputed scores in the browser. Every score includes all eligible citation depths.

## Run locally

```sh
python -m pip install -r requirements.txt
python effective_citations.py --rates 0.5 1
mkdir -p dist
cp -R web/. dist/
python build_browser_data.py inspire_scores.csv.gz dist/data
python -m http.server 8000 --directory dist
```

Open `http://localhost:8000`. The first run downloads the graph ZIP from [Netzschleuder](https://networks.skewed.de/net/inspire_hep). Pass `--snapshot PATH` to reuse a local copy or `--lookup` to print selected results from the command line. The score CSV contains all indexed records and both rates.

## GitHub Pages

Choose **Settings → Pages → Source → GitHub Actions**. The Pages workflow builds the static site and runs the scorer in GitHub Actions. It can also be run manually from the Actions tab. GitHub Pages eligibility depends on repository visibility and the account plan.

GitHub checks the snapshot every Monday at 04:17 UTC. It downloads and scores a new archive only when its ETag differs from the live version. Pushes to `main` and manual runs rebuild the site. The calculator shows the archive date and the most recent successful check. GitHub may disable the weekly schedule after 60 days without repository activity.

## Scoring

A direct citation earns one point. If B cites A, A also earns the selected fraction of B's effective score. Separate routes contribute independently, including routes through the same later paper. Each link counts once between a given pair of records. The scorer keeps a link when the citing record is clearly dated later and follows every eligible branch to its end.

The initial run scored 1,897,471 records and 44,407,154 date-ordered links. The source snapshot has SHA-256 `d2f117572e551a8b7f814f08248562f7dc14884c9af2bd21b19622cdd0fdb4eb`. The default download follows the provider's current copy, so later builds may use updated data. Direct counts on this site use the same eligible links as the effective scores.
