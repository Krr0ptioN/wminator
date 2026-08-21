#![forbid(unsafe_code)]

pub mod adapters;
pub mod application;
pub mod domain;
pub mod error;
pub mod ports;

pub use error::{Result, WminatorError};
