from pathlib import Path
import os

from setuptools import setup, glob, find_packages

PROJECT_DIR = Path(__file__).parent.resolve()
README_FILE = PROJECT_DIR / "README.md"
VERSION = "0.0.3"

with open("requirements.txt") as f:
    INSTALL_REQUIRES = f.read().splitlines()

PACKAGE_FILES = []
for (path, directories, filenames) in os.walk('hass_client/'):
    for filename in filenames:
        PACKAGE_FILES.append(os.path.join('..', path, filename))

setup(
    name="hass_client",
    version=VERSION,
    url="https://github.com/marcelveldt/python-hass-client",
    download_url="https://github.com/marcelveldt/python-hass-client",
    author="Marcel van der Veldt",
    author_email="m.vanderveldt@outlook.com",
    description="Basic client for connecting to Home Assistant over websockets and REST.",
    long_description=README_FILE.read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    packages=find_packages(exclude=["test.*", "test"]),
    python_requires=">=3.7",
    include_package_data=True,
    install_requires=INSTALL_REQUIRES,
    package_data={
        'hass_client': PACKAGE_FILES,
    },
    zip_safe=False,
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Natural Language :: English",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Topic :: Home Automation",
    ],
)
