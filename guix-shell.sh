#!/usr/bin/env bash

guix shell -CWNF --manifest=manifest.scm --share=.local="$HOME/.local" "$@"
