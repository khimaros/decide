SITE_DIR ?= site
SITE_PORT ?= 8080
DECIDE = target/release/decide

# npm writes into node_modules constantly, so the directory's own timestamp
# says nothing about whether the install matches the manifest. stamp instead.
NODE_MODULES = web/node_modules/.stamp

.DEFAULT_GOAL := build

build: site
.PHONY: build

site: assets generator
	$(DECIDE) build --output $(SITE_DIR)
.PHONY: site

check: generator
	$(DECIDE) check
	$(DECIDE) fmt --check
.PHONY: check

fmt: generator
	$(DECIDE) fmt
.PHONY: fmt

serve: site
	python3 -m http.server --directory $(SITE_DIR) $(SITE_PORT)
.PHONY: serve

generator:
	cargo build --release
.PHONY: generator

assets: $(NODE_MODULES)
	npm --prefix web run build
	cp web/static/logo.svg web/dist/logo.svg
.PHONY: assets

$(NODE_MODULES): web/package.json web/package-lock.json
	npm --prefix web ci
	touch $@

test: $(NODE_MODULES)
	cargo test
	npm --prefix web run check
.PHONY: test

test-e2e: build
	python3 -m unittest discover --start-directory e2e --pattern '*_test.py' --top-level-directory .
.PHONY: test-e2e

precommit: test test-e2e check
	cargo fmt --check
	cargo clippy --all-targets -- -D warnings
.PHONY: precommit

clean:
	rm -rf $(SITE_DIR) target web/dist web/node_modules
.PHONY: clean
