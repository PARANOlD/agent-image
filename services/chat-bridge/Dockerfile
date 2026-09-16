FROM python:3.12-slim

# Needed by github_pr_creator.py to actually clone/branch/commit/push --
# everything else chat-bridge does is API calls, this is the one place it
# shells out to a real git checkout.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "app.py"]
