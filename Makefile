MAKECMDGOALS := $(filter-out build-prod,$(MAKECMDGOALS))

# Forward all targets to just
.PHONY: _just_default_ $(MAKECMDGOALS)
_just_default_ $(MAKECMDGOALS) &::
	$(warning $(shell tput bold setaf 1)Use just instead of make.$(shell tput sgr0))
	@just $(MAKECMDGOALS)

build-prod:
	_plugins/last_update_git_fetch.sh
	bundle exec jekyll build --verbose --trace
