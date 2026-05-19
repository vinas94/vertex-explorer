# 1. list available auto fixes from linter (ruff check --diff)
# 2. list available auto fixes from formatter (ruff format --diff)
# 3. run the fixes
# 4. count and print unique files from both lists
format:
	@files=$$(( \
		uv run ruff check --exclude '*.ipynb' --extend-select I --line-length=120 --ignore F401 --diff | grep "^---" | cut -c5-; \
		uv run ruff format --exclude '*.ipynb' --line-length=120 --diff 2>/dev/null | grep "^---" | cut -c5-; \
	) | sort -u | grep .); \
	if [ -n "$$files" ]; then \
	    uv run ruff check --exclude '*.ipynb' --extend-select I --line-length=120 --ignore F401 --fix >/dev/null 2>&1; \
		uv run ruff format --exclude '*.ipynb' --line-length=120 >/dev/null 2>&1; \
		echo "$$files" | wc -l | xargs printf "%d file(s) were formatted:\n"; \
		echo "$$files"; \
	else \
	   echo "Nothing to format!"; \
	fi

# || true is just to suppress non-zero exit code when issues are found
lint:
	@uv run ruff check --exclude '*.ipynb' --output-format=concise --ignore E731 || true

test:
	@uv run pytest -q tests/
