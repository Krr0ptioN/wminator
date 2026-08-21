.DEFAULT_GOAL := help

.PHONY: build install lint format test check clean help

build:          ## Build a debug binary
	cargo build --locked
install:        ## Install wminator for the current user
	cargo install --locked --path .
lint:           ## Run Clippy with warnings denied
	cargo clippy --all-targets --all-features -- -D warnings
format:         ## Format Rust sources
	cargo fmt
test:           ## Run all tests
	cargo test --all-features
check:          ## Run the complete local CI suite
	cargo fmt --check
	cargo clippy --all-targets --all-features -- -D warnings
	cargo test --all-features
clean:          ## Remove Cargo build artifacts
	cargo clean
help:           ## Show this help
	@awk 'BEGIN {FS = ":.*?## "}; /^[a-zA-Z_-]+:.*?## / {printf "%-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
