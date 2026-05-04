FROM python:3.12-slim

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies required for Poetry and other tools
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    git \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 -

# Add Poetry to the PATH
ENV PATH="/root/.local/bin:$PATH"

# Set default environment variables (can be overridden by docker-compose)
ENV APP_ENV=production
ENV LOG_LEVEL=INFO

# Verify Poetry installation
RUN poetry --version

# Copy only the poetry.lock and pyproject.toml first for caching dependencies
COPY pyproject.toml poetry.lock ./

# Install dependencies using Poetry
RUN poetry install --no-root --only main

# Ensure Poetry's virtual environment is activated
RUN poetry config virtualenvs.in-project true

# Copy the rest of your application code
COPY . /app

# Expose the port your application will run on (adjust port if needed)
EXPOSE 80

# Use the Poetry virtual environment's Uvicorn for running the app
CMD ["poetry", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80", "--workers", "4"]
