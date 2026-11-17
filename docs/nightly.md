# The nightly, its source, and its rehearsals

## What a night scores

The night scores every anchor unit of the substrate release that the scored inference-sim release pins (COV-1, COV-2). It reads each unit's record from the ledger's own pinned source, the InferenceX dump named in blis-substrate's `catalog/ledger/sources.yaml` (design §2.2). It never reads the live API's 180-day window. So a unit is scored on the record the ledger was made from, whatever its age:

- An anchor the source holds no record of is G5 `value_not_recorded:anchor_not_in_source`, and the rest are scored.
- An anchor the ledger does not hold stops the night, because the anchor list and the ledger are then not one release's.
- A live API row of the last 180 days whose content differs from the source's record is not scored. It is listed in the backlog as a `later_ledger_candidates` entry: a candidate for a ledger pinned to a newer snapshot.

## The ledger extract

The dump is 34 GB, and its restore (17 GB) does not fit a standard runner. The night reads the ledger extract instead (`orchestrator/ingest/ledger_extract.py`), a single gzip JSON-lines file that holds:

- every dump row, exactly as the substrate's `ledger/inferencex/export.sql` prints it;
- the pinned supplements, fetched by the substrate's own `ledger supplement-records`;
- the vLLM server log of each anchor record the scorer reads a log for.

Lines are in row-id order, and gzip writes no name and no time, so the same dump gives the same bytes.

| | blis-substrate v0.14.1 |
|---|---|
| Ledger revision | `db-dump/2026-09-28` |
| Bytes | 199,887,567 |
| Rows | 85,325 (85,309 from the dump, 16 supplements) |
| Logs | 2,110 |
| Units | 82,347, exactly the ledger's |
| sha256 | `70d4ef41ed588fa73f7e1a007dcc76e55abff60412723709ed9f13226048a55a` |

`.github/ledger-extract.json` pins the extract: its sha256, size, ledger revision, and a digest of what it is made from (the pinned dump, the supplements and the anchor list). Before reading the extract, the night checks the sha256, size and ledger revision. It also checks that the extract's rows place no unit the ledger lacks.

**Building it.** The `ledger-extract` workflow builds the extract for a substrate release with `orchestrator/ingest/build_ledger_extract.sh`:

1. It restores four tables of the pinned dump into a scratch PostgreSQL 17 cluster, checking each part against its SHA-256.
2. It writes the extract, then checks that its rows place exactly the ledger's units.
3. It prints the pin to commit.

The nightly runs the same script when its cache misses, and refuses a result whose bytes are not the pin's.

**Redistribution (X12).** `sources.yaml` records the InferenceX data's licence as NOASSERTION. The extract is therefore never committed, never a release asset and never published. It lives only in this repository's Actions cache (keyed by its sha256) and in the build's 90-day artifact. A lost entry is rebuilt by running the workflow again.

## The frozen pull

The extract holds the rows and the logs. Everything else a point needs came from GitHub run by run: artifact listings, agentic exports, launch configs, the client job logs, the P/D recipes at the run's commit, and the build resolver's vLLM commit lookups. A night that asked for all of these each time spent the REST budget every agent and workflow shares, and broke when an artifact expired.

`orchestrator/ingest/freeze_ledger.py` freezes these inputs once per extract into a pull of every anchor unit. It uses the harness's own pull, `cli.cmd_pull`, and packs the result into one archive whose bytes depend only on its files. The night replays the archive, filters it to its anchors, and remakes each build record for the engine release it scores. Every build lookup is answered from the lookups recorded at the freeze, so a night asks GitHub nothing except what a new engine release adds. The night logs that count.

- **Fewer requests.** The P/D recipes and the resolver's commit questions are read from blobless clones of InferenceX and vLLM (`gitlocal.py`), and each run's head commit from the extract (`run_head_sha`). Only artifact listings, artifact downloads and the job-log archives use REST: one archive per run, not one request per job.
- **Resumable and throttled.** A point already frozen is kept, and the freeze reads the REST budget before each batch (`GET /rate_limit` spends none). It never spends more than a set number of requests an hour, and waits for the reset below a floor. In Actions, run-night freezes on a cache miss at 900 an hour on its own token. A run that does not finish keeps its partial freeze, and the next run continues from it.
- **Decided once.** A unit whose inputs GitHub no longer held at the freeze is G5 with the reason the pull names it, such as `artifact_unmatched:run_gone_404` or `server_log_missing:not_in_source`.
- **Pinned.** The archive's sha256 and size go beside the extract's, as `pull` in `.github/ledger-extract.json`, and the night checks them before it unpacks. It refuses an entry that is not a file inside the pull. Like the extract, the archive is third-party data: it is kept in the Actions cache only.

## Rehearsals

`api-nightly.yml` has a `dry_run` input. With it, resolve and run-night run as always, and the publish job runs every validation:

- unpack;
- `validate_summary_v2`;
- the COV-7 coverage and backlog checks;
- the experimental check;
- the dump-snapshot diff;
- the state files.

It then prints what it would publish (snapshot id, release, points, graded, grades) and stops before the commit, the push, the Pages deploy and the next run. A scheduled run has no inputs and publishes as before.

`nightly-rehearsal.yml` calls it as a dry run:

- **On a pull request** that changes `orchestrator/`, `harness/`, the nightly or the extract's pin. It scores a fixed, seeded draw of about 200 anchor units (`cli.py nightly --sample`). The draw first takes one unit for every model, chip, framework and engine image the anchors hold, then fills to 200 at random. It uses the release the nightly would score next. A scorer change thus proves that the nightly still publishes before it merges. The budget is about 15 minutes, with the extract and artifacts taken from the cache.
- **Every day.** It scores the same draw with the newest inference-sim release, so a release that will not score fails the day it is tagged. It also checks that the newest blis-substrate release's ledger source is the one the extract was built from (`ledger_extract.py check-source`). If not, it fails, naming the workflow to run.
