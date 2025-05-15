FROM mcr.microsoft.com/devcontainers/python:3.13-bookworm

RUN <<EOF
set -eu

apt-get update
apt-get install -y --no-install-recommends pipx

pipx install uv
EOF
