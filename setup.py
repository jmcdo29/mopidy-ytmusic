# -*- coding: utf-8 -*-
from setuptools import setup

packages = \
['mopidy_ytmusic']

package_data = \
{'': ['*']}

install_requires = \
['Mopidy>=3,<4', 'pytube>=12.1.0', 'ytmusicapi>=1.0']

entry_points = \
{'mopidy.ext': ['ytmusic = mopidy_ytmusic:Extension']}

setup_kwargs = {
    'name': 'Mopidy-YTMusic',
    'version': '0.3.9',
    'description': 'Mopidy extension for playling music/managing playlists in Youtube Music',
    'long_description': 'None',
    'author': 'Ozymandias (Tomas Ravinskas)',
    'author_email': 'tomas.rav@gmail.com',
    'maintainer': 'None',
    'maintainer_email': 'None',
    'url': 'None',
    'packages': packages,
    'package_data': package_data,
    'install_requires': install_requires,
    'entry_points': entry_points,
    'python_requires': '>=3.8,<4.0',
}


setup(**setup_kwargs)

