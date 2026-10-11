# Montréal Visual Art & Vernissages Calendar

An automatically refreshed calendar of vernissages, artist talks, tours, workshops, launches, and other scheduled visual-art events in Montréal.

The feed intentionally excludes ordinary multi-week exhibition date ranges. Current sources are Réseau Art Actuel, the Canadian Centre for Architecture, and the Centre de design de l’UQAM. It uses `America/Toronto`, stable event identifiers, deduplication, original links, and two-run cancellation handling.

Website: https://k10sj02.github.io/montreal-visual-art-calendar/

Subscription: https://k10sj02.github.io/montreal-visual-art-calendar/montreal-visual-art.ics

## Local use

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
pytest
montreal-visual-art-calendar
```
