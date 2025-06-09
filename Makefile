BUNDLE ?= bundle

export BUNDLE_PATH ?= $(CURDIR)/.bundle/gems

.PHONY: build
build: .bundle/.done
	$(BUNDLE) exec jekyll build --drafts

.PHONY: serve
serve: .bundle/.done
	$(BUNDLE) exec jekyll serve --drafts --host localhost --port 12345 --livereload

.PHONY: serve
serve-public: .bundle/.done
	$(BUNDLE) exec jekyll serve --drafts --host 0.0.0.0 --port 12123 --livereload --livereload-port 12124

.bundle/.done: Gemfile
	$(BUNDLE) install
	touch $@

.PHONY: clean
clean:
	git clean -ffdX
