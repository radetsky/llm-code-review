package store

import (
	"encoding/json"
	"os"
)

type Config struct {
	Addr    string `json:"addr"`
	Workers int    `json:"workers"`
}

func LoadDefaults() Config {
	return Config{Addr: ":8080", Workers: 4}
}

func LoadConfig(path string) (*Config, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	var cfg Config
	if err := json.NewDecoder(f).Decode(&cfg); err != nil {
		return nil, err
	}
	return &cfg, nil
}
