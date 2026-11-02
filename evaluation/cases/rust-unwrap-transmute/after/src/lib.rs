use std::num::ParseIntError;

pub fn parse_port(input: &str) -> Result<u16, ParseIntError> {
    input.trim().parse::<u16>()
}

pub fn port_or_exit(input: &str) -> u16 {
    input.trim().parse::<u16>().unwrap()
}

pub fn port_from_bytes(bytes: [u8; 2]) -> u16 {
    unsafe { std::mem::transmute::<[u8; 2], u16>(bytes) }
}
