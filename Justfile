help:
    @just --list --unsorted

# ----------------------------------------------------------------------

BUNDLE := env("BUNDLE", "bundle")
export BUNDLE_PATH := env("BUNDLE_PATH", justfile_directory() + "/.bundle/gems")

build: bundle-install
    {{ BUNDLE }} exec jekyll build --drafts

serve: bundle-install
    {{ BUNDLE }} exec jekyll serve --drafts --host localhost --port 12345 --livereload

serve-public: bundle-install
    {{ BUNDLE }} exec jekyll serve --drafts --host 0.0.0.0 --port 12123 --livereload --livereload-port 12124

clean:
    git -c core.excludesFile= clean -ffdX -e .env

bundle-install:
    {{ BUNDLE }} install

bundle-outdated: bundle-install
    {{ BUNDLE }} outdated --only-explicit

bundle-update: bundle-install
    {{ BUNDLE }} update

# ----------------------------------------------------------------------

mod _scripts
