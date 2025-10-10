#!/bin/bash
# Set environment variables to disable TensorFlow in transformers
export TRANSFORMERS_NO_TF=1
export TF_USE_LEGACY_KERAS=1
export TF_CPP_MIN_LOG_LEVEL=3

# Run the test script
python test_semantic_integration.py
