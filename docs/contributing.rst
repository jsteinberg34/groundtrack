Contributing
============

Contributions are welcome. Whether you're fixing a bug, improving documentation, or proposing a new feature, please follow the steps below.

Getting Started
---------------

1. Fork the repository on GitHub
2. Clone your fork locally:

.. code-block:: bash

   git clone https://github.com/your-username/groundtrack.git
   cd groundtrack

3. Create a virtual environment and install the library in editable mode:

.. code-block:: bash

   python -m venv .venv
   source .venv/bin/activate  # on Windows: .venv\Scripts\activate
   pip install -e ".[plotting]"

4. Create a feature branch:

.. code-block:: bash

   git checkout -b feature/your-feature-name

Making Changes
--------------

- Keep changes focused — one feature or fix per pull request
- Follow the existing code style and naming conventions
- Add or update docstrings for any functions you modify
- If you fix a bug, include a description of what was wrong and how you fixed it

Submitting a Pull Request
--------------------------

1. Commit your changes with a clear, imperative commit message (e.g. ``Fix corridor distance calculation for polar orbits``)
2. Push your branch to your fork:

.. code-block:: bash

   git push origin feature/your-feature-name

3. Open a pull request against the ``main`` branch of the original repository
4. Describe what your change does and why

Reporting Bugs
--------------

If you find a bug, please open an issue on `GitHub <https://github.com/jsteinberg34/groundtrack/issues>`_ and include:

- A short description of the problem
- Steps to reproduce it
- The Python version and platform you're running on
- Any relevant error messages or tracebacks

Requesting Features
-------------------

Feature requests are also welcome via `GitHub Issues <https://github.com/jsteinberg34/groundtrack/issues>`_. Please describe the use case and why the feature would be useful.