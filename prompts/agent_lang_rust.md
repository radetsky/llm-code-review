Rust checks:
- An unsafe block without a SAFETY comment is a warning. A wrong unsafe block is critical.
- Report unwrap() and expect() on a value that can fail at run time, for example input or I/O.
- Report std::mem::transmute and raw pointer dereference unless the code shows why they are safe.
- Check each FFI call for a null pointer, a wrong length and a wrong lifetime.
- Report a blocking call in async code and a lock that stays held across an await.
