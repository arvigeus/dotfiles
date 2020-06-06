#!/bin/bash

# https://wiki.debian.org/Fonts

mkdir -p ~/.fonts
# https://design.ubuntu.com/font/
wget https://assets.ubuntu.com/v1/0cef8205-ubuntu-font-family-0.83.zip -O ./ubuntu-font-family.zip
unzip ubuntu-font-family.zip -d ~/.fonts/
rm ./ubuntu-font-family.zip