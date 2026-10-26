help:
    @just --list --unsorted

# ----------------------------------------------------------------------

build: bundle-install
    bundle exec jekyll build --drafts

serve: bundle-install
    bundle exec jekyll serve --drafts --host localhost --port 12345 --livereload

serve-public: bundle-install
    bundle exec jekyll serve --drafts --host 0.0.0.0 --port 12123 --livereload --livereload-port 12124

clean *opts:
    git -c core.excludesFile= clean -ffdX -e '!.env' {{ opts }}

bundle-install:
    bundle install

bundle-outdated: bundle-install
    bundle outdated --only-explicit

bundle-update: bundle-install
    bundle update

# ----------------------------------------------------------------------

mod _scripts
