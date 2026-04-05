// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"sync"
	"time"

	"github.com/hashicorp/golang-lru/v2/expirable"
)

const (
	_overflowValue    = "__overflow__"
	_lruCapMultiplier = 10
	_lruCapMin        = 1000
)

// CardinalityLimit defines the maximum unique values and TTL for an attribute key.
type CardinalityLimit struct {
	MaxValues  int
	TTLSeconds float64
}

var (
	_cardinalityMu     sync.RWMutex
	_cardinalityLimits map[string]CardinalityLimit
	_cardinalityCaches map[string]*expirable.LRU[string, struct{}]
)

func init() {
	_resetCardinalityLimits()
}

// _resetCardinalityLimits clears all limits and caches. Used in tests.
func _resetCardinalityLimits() {
	_cardinalityMu.Lock()
	defer _cardinalityMu.Unlock()
	_cardinalityLimits = make(map[string]CardinalityLimit)
	_cardinalityCaches = make(map[string]*expirable.LRU[string, struct{}])
}

// SetCardinalityLimit configures the max-values and TTL for a specific attribute key.
func SetCardinalityLimit(key string, limit CardinalityLimit) {
	_cardinalityMu.Lock()
	defer _cardinalityMu.Unlock()
	_cardinalityLimits[key] = limit
	// Evict any existing cache so it is rebuilt with the new limit.
	delete(_cardinalityCaches, key)
}

// GetCardinalityLimit returns the configured limit for key, or a zero value if unset.
func GetCardinalityLimit(key string) CardinalityLimit {
	_cardinalityMu.RLock()
	defer _cardinalityMu.RUnlock()
	return _cardinalityLimits[key]
}

// _lruForKey returns (or creates) the expirable LRU for the given key.
// Caller must hold _cardinalityMu write lock.
func _lruForKey(key string, limit CardinalityLimit) *expirable.LRU[string, struct{}] {
	if cache, ok := _cardinalityCaches[key]; ok {
		return cache
	}
	cap := max(limit.MaxValues*_lruCapMultiplier, _lruCapMin)
	ttl := time.Duration(float64(time.Second) * limit.TTLSeconds)
	cache := expirable.NewLRU[string, struct{}](cap, nil, ttl)
	_cardinalityCaches[key] = cache
	return cache
}

// _guardValue checks a single attribute value against its limit cache.
// Returns the value to use in the output map.
func _guardValue(key, value string, limit CardinalityLimit) string {
	_cardinalityMu.Lock()
	cache := _lruForKey(key, limit)
	_, exists := cache.Get(value)
	if exists {
		_cardinalityMu.Unlock()
		return value
	}
	if cache.Len() >= limit.MaxValues {
		_cardinalityMu.Unlock()
		return _overflowValue
	}
	cache.Add(value, struct{}{})
	_cardinalityMu.Unlock()
	return value
}

// GuardAttributes returns a new map with attribute values replaced by "__overflow__"
// when their key has exceeded its configured cardinality limit.
// Input map is never mutated.
func GuardAttributes(attrs map[string]string) map[string]string {
	result := make(map[string]string, len(attrs))
	for key, value := range attrs {
		_cardinalityMu.RLock()
		limit, hasLimit := _cardinalityLimits[key]
		_cardinalityMu.RUnlock()

		if !hasLimit {
			result[key] = value
			continue
		}
		result[key] = _guardValue(key, value, limit)
	}
	return result
}
