"""Model tester: compare how different Ollama models handle the program's own steps.

    python -m tools.model_test docs --profiles software it_support --models qwen2.5:7b llama3.1:8b --url <job url>

    python -m tools.model_test score --profiles software --models qwen2.5:7b llama3.1:8b --url <job url>
    python -m tools.model_test compare --run <run name>        # side by side in the terminal; add --html for a web page

It only controls the program's existing code (documents/application_maker.py and friends); nothing is copied.
Results go to data/model_tests/<run>/ and never touch your jobs database or calibration.
"""
