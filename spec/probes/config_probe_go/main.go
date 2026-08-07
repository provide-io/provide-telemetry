// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
// Emit observed config metadata for the Go SDK.
//
// The probe never reads spec/telemetry-api.yaml. Applicability is determined
// differentially: build the config with a clean environment for the baseline,
// then rebuild once per variable with that variable set. A variable this SDK
// parses changes the config; one it ignores leaves it identical. The reported
// default and type come from the baseline config object.
package main

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
	"reflect"
	"sort"
	"strconv"
	"strings"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

// Values chosen to differ from every spec default, including valid values for
// validated fields (a rejected value proves the variable is read but leaves no
// config object to diff).
var probeValues = []string{
	"DEBUG",
	"json",
	"red",
	"3",
	"1327",
	"0.4271",
	"probe-sentinel-value",
	"false",
	"true",
	"http://probe.invalid:4318",
	"probe-module=DEBUG",
	"probe-key=probe-value",
}

var ownedPrefixes = []string{"PROVIDE_", "OTEL_"}

type entry struct {
	Type       string `json:"type"`
	Default    string `json:"default"`
	Applicable bool   `json:"applicable"`
}

type payload struct {
	Language string           `json:"language"`
	Entries  map[string]entry `json:"entries"`
}

func owned(key string) bool {
	for _, p := range ownedPrefixes {
		if strings.HasPrefix(key, p) {
			return true
		}
	}
	return false
}

func cleanEnv() map[string]string {
	env := map[string]string{}
	for _, kv := range os.Environ() {
		parts := strings.SplitN(kv, "=", 2)
		if len(parts) == 2 && !owned(parts[0]) {
			env[parts[0]] = parts[1]
		}
	}
	return env
}

// flatten walks the config struct into dotted-path -> stringified scalar. Maps
// and slices render as strings so comparison is by value: comparing them as
// composites would make every field look changed on every call.
func flatten(v reflect.Value, prefix string, out map[string]string) {
	switch v.Kind() {
	case reflect.Struct:
		t := v.Type()
		for i := 0; i < v.NumField(); i++ {
			if !t.Field(i).IsExported() {
				continue
			}
			flatten(v.Field(i), prefix+t.Field(i).Name+".", out)
		}
	case reflect.Ptr, reflect.Interface:
		if v.IsNil() {
			out[strings.TrimSuffix(prefix, ".")] = ""
			return
		}
		flatten(v.Elem(), prefix, out)
	case reflect.Map:
		keys := make([]string, 0, v.Len())
		for _, k := range v.MapKeys() {
			keys = append(keys, fmt.Sprint(k.Interface()))
		}
		sort.Strings(keys)
		pairs := make([]string, 0, len(keys))
		for _, k := range keys {
			pairs = append(pairs, k+"="+fmt.Sprint(v.MapIndex(reflect.ValueOf(k)).Interface()))
		}
		out[strings.TrimSuffix(prefix, ".")] = strings.Join(pairs, ",")
	case reflect.Slice, reflect.Array:
		items := make([]string, 0, v.Len())
		for i := 0; i < v.Len(); i++ {
			items = append(items, fmt.Sprint(v.Index(i).Interface()))
		}
		out[strings.TrimSuffix(prefix, ".")] = strings.Join(items, ",")
	default:
		out[strings.TrimSuffix(prefix, ".")] = render(v)
	}
}

func render(v reflect.Value) string {
	switch v.Kind() {
	case reflect.Bool:
		if v.Bool() {
			return "true"
		}
		return "false"
	case reflect.Float32, reflect.Float64:
		return strconv.FormatFloat(v.Float(), 'g', -1, 64)
	default:
		return fmt.Sprint(v.Interface())
	}
}

func typeName(v reflect.Value) string {
	switch v.Kind() {
	case reflect.Bool:
		return "bool"
	case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64,
		reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32, reflect.Uint64:
		return "int"
	case reflect.Float32, reflect.Float64:
		return "float"
	default:
		return "str"
	}
}

// typesOf records each flattened path's declared kind so the reported type
// comes from the struct field, not from the rendered string.
func typesOf(v reflect.Value, prefix string, out map[string]string) {
	switch v.Kind() {
	case reflect.Struct:
		t := v.Type()
		for i := 0; i < v.NumField(); i++ {
			if !t.Field(i).IsExported() {
				continue
			}
			typesOf(v.Field(i), prefix+t.Field(i).Name+".", out)
		}
	case reflect.Ptr, reflect.Interface:
		if v.IsNil() {
			out[strings.TrimSuffix(prefix, ".")] = "str"
			return
		}
		typesOf(v.Elem(), prefix, out)
	case reflect.Map, reflect.Slice, reflect.Array:
		out[strings.TrimSuffix(prefix, ".")] = "str"
	default:
		out[strings.TrimSuffix(prefix, ".")] = typeName(v)
	}
}

func build(env map[string]string) (map[string]string, map[string]string, error) {
	saved := os.Environ()
	os.Clearenv()
	for k, v := range env {
		_ = os.Setenv(k, v)
	}
	defer func() {
		os.Clearenv()
		for _, kv := range saved {
			parts := strings.SplitN(kv, "=", 2)
			if len(parts) == 2 {
				_ = os.Setenv(parts[0], parts[1])
			}
		}
	}()

	cfg, err := telemetry.ConfigFromEnv()
	if err != nil {
		return nil, nil, err
	}
	values := map[string]string{}
	kinds := map[string]string{}
	flatten(reflect.ValueOf(cfg).Elem(), "", values)
	typesOf(reflect.ValueOf(cfg).Elem(), "", kinds)
	return values, kinds, nil
}

// defaultInVariableUnits expresses a numeric default in the units the
// environment variable uses. An SDK may store a `..._TIMEOUT_SECONDS` value as
// milliseconds; rather than hardcoding which fields are scaled, measure the
// SDK's own conversion factor from a known probe value.
func defaultInVariableUnits(baseline, probeValue, observed string) string {
	base, err1 := strconv.ParseFloat(baseline, 64)
	probed, err2 := strconv.ParseFloat(probeValue, 64)
	obs, err3 := strconv.ParseFloat(observed, 64)
	if err1 != nil || err2 != nil || err3 != nil || probed == 0 || obs == 0 {
		return baseline
	}
	scale := obs / probed
	if scale == 1 || scale <= 0 || scale != math.Trunc(scale) {
		return baseline
	}
	return strconv.FormatFloat(base/scale, 'g', -1, 64)
}

func observe(envVars []string) map[string]entry {
	baseEnv := cleanEnv()
	baseline, kinds, err := build(baseEnv)
	if err != nil {
		fmt.Fprintf(os.Stderr, "baseline config failed: %v\n", err)
		os.Exit(1)
	}

	entries := map[string]entry{}
	for _, envVar := range envVars {
		settled := false
		rejected := false
		for _, probeValue := range probeValues {
			env := map[string]string{}
			for k, v := range baseEnv {
				env[k] = v
			}
			env[envVar] = probeValue

			observed, _, err := build(env)
			if err != nil {
				rejected = true // a rejected value still proves the variable is read
				continue
			}
			changed := []string{}
			for k, v := range baseline {
				if ov, ok := observed[k]; ok && ov != v {
					changed = append(changed, k)
				}
			}
			if len(changed) > 0 {
				sort.Strings(changed)
				key := changed[0]
				entries[envVar] = entry{
					Type:       kinds[key],
					Default:    defaultInVariableUnits(baseline[key], probeValue, observed[key]),
					Applicable: true,
				}
				settled = true
				break
			}
		}
		if !settled {
			entries[envVar] = entry{Type: "", Default: "", Applicable: rejected}
		}
	}
	return entries
}

func main() {
	envVars := os.Args[1:]
	if len(envVars) == 0 {
		fmt.Fprintln(os.Stderr, "usage: config_probe_go ENV_VAR [ENV_VAR ...]")
		os.Exit(2)
	}
	out, err := json.Marshal(payload{Language: "go", Entries: observe(envVars)})
	if err != nil {
		fmt.Fprintf(os.Stderr, "marshal failed: %v\n", err)
		os.Exit(1)
	}
	fmt.Println(string(out))
}
