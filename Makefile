.PHONY: dev install clean

# Setup dependencies for both backend and frontend
install:
	@echo "Installing backend dependencies..."
	cd backend && python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
	@echo "Installing frontend dependencies..."
	cd frontend && npm install

# Run both services concurrently
dev:
	npx --yes concurrently --kill-others --names "BACKEND,FRONTEND" --prefix-colors "blue,green" \
		"cd backend && ./venv/bin/python main.py" \
		"cd frontend && npm run dev"

# Clean up build artifacts and dependencies
clean:
	rm -rf backend/venv backend/__pycache__
	rm -rf frontend/node_modules frontend/dist
