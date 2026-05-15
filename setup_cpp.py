"""Build the optional pybind11 execution engine in place."""

import pybind11
from setuptools import Extension, setup

setup(
    name="ordersim-cpp",
    ext_modules=[
        Extension(
            "ordersim._matching_engine_cpp",
            ["cpp/matching_engine_cpp.cpp"],
            include_dirs=[pybind11.get_include(), "cpp"],
            language="c++",
            extra_compile_args=["-O3", "-std=c++17"],
        )
    ],
    package_dir={"": "src"},
)
