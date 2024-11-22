# cargo eclass

if [[ -n ${CARGO_OPTIONAL} ]]; then
	RUST_OPTIONAL=1
fi

inherit rust

CARGO_CRATE_URIS=${CRATES}

cargo_crate_uris() { :; }
