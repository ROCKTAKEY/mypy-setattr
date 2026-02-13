#!/usr/bin/env bash

guix time-machine -C channels.scm -- shell -CWNF --manifest=manifest.scm --share=.local="$HOME/.local" "$@"
