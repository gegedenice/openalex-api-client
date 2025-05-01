from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="openalex-api-client",
    version="0.1.0",
    author="Géraldine geoffroy",
    author_email="grldn.geoffroy@gmail.com",
    description="A Python client for interacting with the OpenAlex API",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/gegedenice/openalex-api-client",
    packages=find_packages(include=['openalex_api_client', 'openalex_api_client.*']),
    include_package_data=True,
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ],
    python_requires=">=3.7",
    install_requires=[
        "requests>=2.25.0",
        "pandas>=1.2.0",
        "numpy>=1.19.0",
        "datasets>=1.5.0",
        "huggingface_hub>=0.0.8",
    ],
    project_urls={
        "Bug Reports": "https://github.com/gegedenice/openalex-api-client/issues",
        "Source": "https://github.com/gegedenice/openalex-api-client",
    },
) 