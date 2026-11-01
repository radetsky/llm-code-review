Go checks:
- Report an error value that the code ignores or assigns to the blank identifier.
- Report a goroutine that has no way to stop, and a channel that no code closes.
- Report a write to a shared variable from many goroutines without a lock.
- Report defer inside a loop, and a write to a nil map.
- Report a missing cancel call after context.WithCancel or context.WithTimeout.
