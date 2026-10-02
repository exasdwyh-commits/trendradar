.PHONY: install dev serve seed-demo daily brief test lint web-build web-dev clean

install:            ## backend (editable) + frontend deps
	pip install -e ".[dev]"
	cd frontend && npm install

dev: web-build      ## build UI once, then run API + UI on :8787 with autoreload
	trendradar serve --reload

serve: web-build    ## production-style: API + built UI + in-process daily scheduler
	trendradar serve --scheduler

seed-demo:          ## run the pipeline on the bundled demo fixtures (no API keys)
	trendradar init
	trendradar seed-demo

daily:              ## run the daily pipeline once against live sources
	trendradar daily

brief:              ## fetch business sources and rebuild today's 简报 only (no clustering/analysis)
	trendradar brief

test:
	pytest -q

lint:
	ruff check src tests
	ruff format --check src tests

web-build:
	cd frontend && npm run build

web-dev:            ## Vite dev server on :5173 proxying /api to :8787
	cd frontend && npm run dev

clean:
	rm -rf data/*.db data/*.db-* frontend/dist
