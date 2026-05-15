"""Build the packaged pybind11 execution engine."""

from pybind11.setup_helpers import Pybind11Extension, build_ext
from setuptools import setup

setup(
    ext_modules=[
        Pybind11Extension(
            "ordersim._matching_engine_cpp",
            ["cpp/matching_engine_cpp.cpp"],
            include_dirs=["cpp"],
            cxx_std=17,
        )
    ],
    cmdclass={"build_ext": build_ext},
)
