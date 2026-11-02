use std::num::ParseIntError;

pub fn parse_port(input: &str) -> Result<u16, ParseIntError> {
    input.trim().parse::<u16>()
}
