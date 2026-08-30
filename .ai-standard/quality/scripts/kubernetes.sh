#!/usr/bin/env bash
set -euo pipefail

action=${1:-}
shift || true
if [ -z "$action" ]; then
  echo "usage: kubernetes.sh <setup|test|lint|check> [dirs...]" >&2
  exit 2
fi
if [ "$#" -eq 0 ]; then set -- .; fi

portable_find() {
  local dir=$1 name1=$2 name2=${3:-}
  if [ -n "$name2" ]; then
    find "$dir" \
      \( -name .git -o -name .ai-standard -o -name node_modules -o -name .venv -o -name venv -o -name archive -o -name dist -o -name build \) -prune -o \
      \( -name "$name1" -o -name "$name2" \) -type f -print 2>/dev/null
  else
    find "$dir" \
      \( -name .git -o -name .ai-standard -o -name node_modules -o -name .venv -o -name venv -o -name archive -o -name dist -o -name build \) -prune -o \
      -name "$name1" -type f -print 2>/dev/null
  fi
}

charts_in() {
  portable_find "$1" Chart.yaml | sed 's#/Chart.yaml$##'
}

kustomizations_in() {
  portable_find "$1" kustomization.yaml kustomization.yml
}

setup_one() {
  local dir=$1
  echo "==> Kubernetes tool preflight: $dir"
  if [ -n "$(charts_in "$dir")" ]; then
    command -v helm >/dev/null 2>&1 || { echo "ERROR: Helm chart detected but helm is not installed" >&2; exit 2; }
  fi
  if [ -n "$(kustomizations_in "$dir")" ]; then
    if ! command -v kustomize >/dev/null 2>&1 && ! command -v kubectl >/dev/null 2>&1; then
      echo "ERROR: kustomization detected but neither kustomize nor kubectl is installed" >&2
      exit 2
    fi
  fi
}

test_one() {
  echo "INFO: Kubernetes profile has no live-cluster tests by default"
}

lint_one() {
  local dir=$1 found=0 chart kfile kdir
  while IFS= read -r chart; do
    [ -n "$chart" ] || continue
    found=1
    command -v helm >/dev/null 2>&1 || { echo "ERROR: helm is required to lint $chart" >&2; exit 2; }
    echo "==> helm lint: $chart"
    helm lint "$chart"
  done < <(charts_in "$dir")

  while IFS= read -r kfile; do
    [ -n "$kfile" ] || continue
    found=1
    kdir=$(dirname "$kfile")
    echo "==> kustomize build: $kdir"
    if command -v kustomize >/dev/null 2>&1; then
      kustomize build "$kdir" >/dev/null
    elif command -v kubectl >/dev/null 2>&1; then
      kubectl kustomize "$kdir" >/dev/null
    else
      echo "ERROR: kustomize or kubectl is required for $kdir" >&2
      exit 2
    fi
  done < <(kustomizations_in "$dir")

  if [ "$found" -eq 0 ]; then
    echo "INFO: no Helm chart or Kustomize root detected under $dir"
  fi
}

check_one() {
  local dir=$1 chart kfile kdir tmp
  while IFS= read -r chart; do
    [ -n "$chart" ] || continue
    command -v helm >/dev/null 2>&1 || { echo "ERROR: helm is required to render $chart" >&2; exit 2; }
    echo "==> helm template: $chart"
    helm template aes-check "$chart" >/dev/null
  done < <(charts_in "$dir")

  while IFS= read -r kfile; do
    [ -n "$kfile" ] || continue
    kdir=$(dirname "$kfile")
    echo "==> render kustomization: $kdir"
    if command -v kustomize >/dev/null 2>&1; then
      kustomize build "$kdir" >/dev/null
    elif command -v kubectl >/dev/null 2>&1; then
      kubectl kustomize "$kdir" >/dev/null
    else
      echo "ERROR: kustomize or kubectl is required for $kdir" >&2
      exit 2
    fi
  done < <(kustomizations_in "$dir")

  if command -v kubeconform >/dev/null 2>&1; then
    while IFS= read -r chart; do
      [ -n "$chart" ] || continue
      tmp=$(mktemp)
      helm template aes-check "$chart" > "$tmp"
      kubeconform -strict -ignore-missing-schemas "$tmp"
      rm -f "$tmp"
    done < <(charts_in "$dir")

    while IFS= read -r kfile; do
      [ -n "$kfile" ] || continue
      kdir=$(dirname "$kfile")
      tmp=$(mktemp)
      if command -v kustomize >/dev/null 2>&1; then
        kustomize build "$kdir" > "$tmp"
      else
        kubectl kustomize "$kdir" > "$tmp"
      fi
      kubeconform -strict -ignore-missing-schemas "$tmp"
      rm -f "$tmp"
    done < <(kustomizations_in "$dir")
  fi
}

for dir in "$@"; do
  [ -d "$dir" ] || { echo "ERROR: Kubernetes directory not found: $dir" >&2; exit 2; }
  case "$action" in
    setup) setup_one "$dir" ;;
    test) test_one "$dir" ;;
    lint) lint_one "$dir" ;;
    check) check_one "$dir" ;;
    *) echo "ERROR: unknown action: $action" >&2; exit 2 ;;
  esac
done
