//! Python bindings for Brave's `adblock-rust` (vendored in ../adblock-rust), written for Null Browser.
//!
//! Design notes
//! * The engine is built **without** the crate's `single-thread` feature, so it is `Send + Sync`: Qt WebEngine calls the
//!   request interceptor from Chromium's IO thread while the engine is built / updated from other threads.
//! * Matching (`check`, `cosmetic`, ...) runs with the GIL released, so a busy page never stalls the Python UI thread.
//! * Everything returns plain Python types (tuples / dicts / lists) so the pure-Python fallback can mimic it exactly.

use std::collections::HashSet;
use std::sync::RwLock;

use adblock::lists::{FilterFormat, ParseOptions};
use adblock::request::Request;
use adblock::resources::Resource;
use adblock::{Engine as RawEngine, FilterSet};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict};

#[pyclass(name = "Engine", frozen)]
struct Engine {
    inner: RwLock<RawEngine>,
}

fn parse_opts(format: &str) -> PyResult<ParseOptions> {
    let format = match format {
        "standard" | "abp" | "ubo" => FilterFormat::Standard,
        "hosts" => FilterFormat::Hosts,
        other => return Err(PyValueError::new_err(format!("unknown list format {other:?}"))),
    };
    Ok(ParseOptions { format, ..ParseOptions::default() })
}

#[pymethods]
impl Engine {
    /// Build an engine from `[(list_text, "standard" | "hosts"), ...]`.
    #[staticmethod]
    #[pyo3(signature = (lists, debug=false))]
    fn from_lists(py: Python<'_>, lists: Vec<(String, String)>, debug: bool) -> PyResult<Self> {
        let mut parsed = Vec::with_capacity(lists.len());
        for (text, format) in lists {
            parsed.push((text, parse_opts(&format)?));
        }
        let engine = py.detach(move || {
            let mut set = FilterSet::new(debug);
            for (text, opts) in parsed {
                set.add_filter_list(text, opts);
            }
            RawEngine::new_with_filter_set(set)
        });
        Ok(Engine { inner: RwLock::new(engine) })
    }

    /// Re-create an engine from the bytes returned by `serialize()` (much faster than re-parsing the lists).
    #[staticmethod]
    fn from_serialized(py: Python<'_>, data: &[u8]) -> PyResult<Self> {
        let data = data.to_vec();
        let engine = py
            .detach(move || {
                let mut e = RawEngine::default();
                e.deserialize(&data).map(|_| e)
            })
            .map_err(|e| PyValueError::new_err(format!("cannot load serialized engine: {e:?}")))?;
        Ok(Engine { inner: RwLock::new(engine) })
    }

    fn serialize<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        let bytes = py.detach(|| self.inner.read().unwrap().serialize());
        PyBytes::new(py, &bytes)
    }

    /// Load redirect / scriptlet resources from a JSON array (Brave's `brave-resources.json` format).
    /// Returns how many resources were loaded.
    fn add_resources_json(&self, py: Python<'_>, json: &str) -> PyResult<usize> {
        let resources: Vec<Resource> =
            serde_json::from_str(json).map_err(|e| PyValueError::new_err(format!("bad resources json: {e}")))?;
        let n = resources.len();
        py.detach(|| self.inner.write().unwrap().use_resources(resources));
        Ok(n)
    }

    /// Check a network request.
    ///
    /// `request_type` uses the Adblock Plus names: document, subdocument, stylesheet, script, image, font, media,
    /// object, xmlhttprequest, ping, websocket, csp_report, other.
    ///
    /// Returns `(blocked, redirect, rewritten_url)`; `redirect` is a `data:` URL to load instead of the request,
    /// `rewritten_url` is the URL with tracking parameters stripped (`$removeparam`). Unparsable URLs are allowed.
    #[pyo3(signature = (url, source_url, request_type="other"))]
    fn check(
        &self,
        py: Python<'_>,
        url: &str,
        source_url: &str,
        request_type: &str,
    ) -> (bool, Option<String>, Option<String>) {
        py.detach(|| {
            let req = match Request::new(url, source_url, request_type, "get") {
                Ok(r) => r,
                Err(_) => return (false, None, None),
            };
            let r = self.inner.read().unwrap().check_network_request(&req);
            (r.should_block(), r.redirect, r.rewritten_url)
        })
    }

    /// `Content-Security-Policy` directives to add for a (sub)document request (`$csp` filters), or None.
    fn csp(&self, py: Python<'_>, url: &str, source_url: &str, request_type: &str) -> Option<String> {
        py.detach(|| {
            let req = Request::new(url, source_url, request_type, "get").ok()?;
            self.inner.read().unwrap().get_csp_directives(&req)
        })
    }

    /// Cosmetic resources for a page URL: a dict with `hide_selectors`, `procedural_actions`, `exceptions`
    /// (all lists of str), `injected_script` (str) and `generichide` (bool).
    fn cosmetic<'py>(&self, py: Python<'py>, url: &str) -> PyResult<Bound<'py, PyDict>> {
        let r = py.detach(|| self.inner.read().unwrap().url_cosmetic_resources(url));
        let d = PyDict::new(py);
        let mut hide: Vec<String> = r.hide_selectors.into_iter().collect();
        hide.sort();
        let mut proc_: Vec<String> = r.procedural_actions.into_iter().collect();
        proc_.sort();
        let mut exc: Vec<String> = r.exceptions.into_iter().collect();
        exc.sort();
        d.set_item("hide_selectors", hide)?;
        d.set_item("procedural_actions", proc_)?;
        d.set_item("exceptions", exc)?;
        d.set_item("injected_script", r.injected_script)?;
        d.set_item("generichide", r.generichide)?;
        Ok(d)
    }

    /// Generic hide selectors needed for the classes / ids found on a page (pass `exceptions` from `cosmetic()`).
    fn hidden_class_id_selectors(
        &self,
        py: Python<'_>,
        classes: Vec<String>,
        ids: Vec<String>,
        exceptions: Vec<String>,
    ) -> Vec<String> {
        let exc: HashSet<String> = exceptions.into_iter().collect();
        py.detach(|| self.inner.read().unwrap().hidden_class_id_selectors(classes, ids, &exc))
    }
}

#[pyfunction]
fn engine_version() -> &'static str {
    "adblock-rust 0.13.3"
}

#[pymodule]
fn null_adblock(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Engine>()?;
    m.add_function(wrap_pyfunction!(engine_version, m)?)?;
    m.add("__version__", "1.0.0")?;
    Ok(())
}
