"""
setup.py for psych-evals

Installs the psych_evals package and its CLI entry point.
"""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [
        line.strip()
        for line in fh
        if line.strip() and not line.startswith("#")
    ]

setup(
    name="psych-evals",
    version="0.1.0",
    author="psych-evals contributors",
    description=(
        "Safety evaluation framework for psychiatric AI systems. "
        "Tests hallucination of clinical guidelines and GDPR Article 9 compliance."
    ),
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/adyasha-kunda/psych-evals",
    packages=find_packages(),
    include_package_data=True,
    package_data={
        "": ["evals/**/*.json", "evals/**/*.md"],
    },
    install_requires=requirements,
    python_requires=">=3.10",
    entry_points={
        "console_scripts": [
            "psych-evals=psych_evals.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Intended Audience :: Healthcare Industry",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Software Development :: Testing",
    ],
)
