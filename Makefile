.PHONY: run lint lint-md lint-docker lint-helm test validate-config print-config helm-install helm-uninstall helm-package docker-build docker-run docker-cleanup clean kill-ports

run:
	pipx run poetry run python -m blockchain_exporter.main

kill-ports:
	@echo "Killing processes using ports 8080 and 9100..."
	@-lsof -ti :8080 | xargs kill -9 2>/dev/null || true
	@-lsof -ti :9100 | xargs kill -9 2>/dev/null || true
	@echo "Ports 8080 and 9100 are now free"

lint: lint-md lint-docker lint-helm
	pipx run poetry run ruff check .

lint-md:
	pipx run poetry run mdformat --wrap=keep --check README.md docs

lint-docker:
	@if command -v hadolint >/dev/null 2>&1; then \
		hadolint Dockerfile; \
	elif command -v docker >/dev/null 2>&1; then \
		docker run --rm -i hadolint/hadolint < Dockerfile; \
	else \
		echo "hadolint (or docker + hadolint image) is required for linting the Dockerfile."; \
		echo "Install hadolint (e.g. via Homebrew: brew install hadolint) or Docker, then rerun."; \
		exit 1; \
	fi

lint-helm:
	@if command -v helm >/dev/null 2>&1; then \
		helm lint helm/charts/blockchain-exporter; \
	else \
		echo "helm is required for linting charts. Install helm (https://helm.sh/docs/intro/install/) and rerun."; \
		exit 1; \
	fi

helm-install:
	@if command -v helm >/dev/null 2>&1; then \
		values_arg=""; \
		if [ -n "$(VALUES)" ]; then \
			values_arg=" -f $(VALUES)"; \
		elif [ -f helm/charts/blockchain-exporter/values.local.yaml ]; then \
			values_arg=" -f helm/charts/blockchain-exporter/values.local.yaml"; \
		fi; \
		helm upgrade --install blockchain-exporter helm/charts/blockchain-exporter -n blockchain-exporter --create-namespace$$values_arg; \
	else \
		echo "helm is required to install charts. Install helm (https://helm.sh/docs/intro/install/) and rerun."; \
		exit 1; \
	fi

helm-uninstall:
	@if command -v helm >/dev/null 2>&1; then \
		helm uninstall blockchain-exporter -n blockchain-exporter; \
	else \
		echo "helm is required to uninstall charts. Install helm (https://helm.sh/docs/intro/install/) and rerun."; \
		exit 1; \
	fi

helm-package:
	@if command -v helm >/dev/null 2>&1; then \
		if [ -z "$(VERSION)" ]; then \
			echo "VERSION is required. Usage: make helm-package VERSION=0.1.0"; \
			exit 1; \
		fi; \
		cd helm/charts/blockchain-exporter && \
		helm package . --version $(VERSION) --app-version $(VERSION) && \
		echo "Chart packaged: blockchain-exporter-$(VERSION).tgz"; \
	else \
		echo "helm is required to package charts. Install helm (https://helm.sh/docs/intro/install/) and rerun."; \
		exit 1; \
	fi

test:
	-pipx run poetry run pytest || \ 
		{ status=$$?; [ $$status -eq 5 ] && exit 0 || exit $$status; }

validate-config:
	pipx run poetry run python -m blockchain_exporter.cli $(if $(CONFIG),--config $(CONFIG),)

print-config:
	pipx run poetry run python -m blockchain_exporter.cli --print-resolved $(if $(CONFIG),--config $(CONFIG),)

docker-build:
	docker build -t blockchain-exporter .

docker-run:
	docker run --rm --name blockchain-exporter --env-file .env -p 8080:8080 -p 9100:9100 blockchain-exporter

docker-cleanup:
	-docker stop blockchain-exporter
	-docker rm blockchain-exporter
	docker container prune --force

clean:
	rm -rf .coverage* coverage.xml htmlcov/
	rm -rf .pytest_cache/ .ruff_cache/ .mypy_cache/
	rm -rf dist/ build/
	rm -rf helm/charts/blockchain-exporter/*.tgz
