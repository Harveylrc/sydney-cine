# Manual sessions

One `<venue>.yaml` per venue whose programme we can't scrape (the format is at the
top of `scrapers/manual.py`). The Sydney Cinémathèque is the first: its site is
bot-walled (DECISIONS 2026-10-19), so once a month:

1. Open the Cinémathèque programme in your own browser, select the page (⌘A) and copy (⌘C).
2. In the project folder run:

       pbpaste | .venv/bin/python -m scripts.paste_to_manual sydney-cinematheque

3. Check the sessions it prints (dates, times, titles) and answer `y` to save.
4. Commit and push `manual/sydney-cinematheque.yaml`; the next nightly run publishes it.

Past sessions drop out by themselves. When a file runs out of upcoming sessions
the venue shows nothing and counts as uncovered.
