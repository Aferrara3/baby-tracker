.PHONY: dev install install-db-backups clean

PROFILE ?= baby

ifeq ($(PROFILE),baby)
APP_PROFILE_CONFIG_PATH := app-profiles/baby-app-config.yaml
PROFILE_DB_PATH := database-dev.db
else ifeq ($(PROFILE),habit)
APP_PROFILE_CONFIG_PATH := app-profiles/habit-app-config.yaml
PROFILE_DB_PATH := database-habit-dev.db
else
$(error Unsupported PROFILE '$(PROFILE)'. Use PROFILE=baby or PROFILE=habit)
endif

# Setup dependencies for both backend and frontend
install:
	@echo "Installing backend dependencies..."
	cd backend && python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
	@echo "Installing frontend dependencies..."
	cd frontend && npm install

# Run both services concurrently
dev:
	npx --yes concurrently --kill-others --names "BACKEND,FRONTEND" --prefix-colors "blue,green" \
		"cd backend && DB_PATH=$(PROFILE_DB_PATH) APP_PROFILE_CONFIG_PATH=$(APP_PROFILE_CONFIG_PATH) ./venv/bin/python main.py" \
		"cd frontend && npm run dev"

install-db-backups:
	./scripts/install-db-backup-cron.sh

# Clean up build artifacts and dependencies
clean:
	rm -rf backend/venv backend/__pycache__
	rm -rf frontend/node_modules frontend/dist
