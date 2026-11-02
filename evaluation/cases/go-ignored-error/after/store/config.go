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
	f, _ := os.Open(path)
	defer f.Close()
	var cfg Config
	if err := json.NewDecoder(f).Decode(&cfg); err != nil {
		return nil, err
	}
	return &cfg, nil
}
