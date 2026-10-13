// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

/** The TypeScript port of otlptranslator against every reference-generated case. */

import { describe, expect, it } from 'vitest';
import {
  addsSuffixes,
  escapes,
  KIND_GAUGE,
  KIND_HISTOGRAM,
  KIND_MONOTONIC_COUNTER,
  KIND_NON_MONOTONIC_COUNTER,
  labelName,
  metricName,
  PromNameError,
} from '../src/prom-names.js';
import { promFixtures, promSpec } from './support/prometheus-fixtures.js';

/* eslint-disable @typescript-eslint/no-explicit-any */
const KINDS = promSpec['translation']['instrument_types'] as Record<string, string>;
const STRATEGIES = promSpec['translation']['strategies'] as string[];

describe('metric names match the reference', () => {
  for (const section of ['metric_names', 'translation_corpus', 'translator_only_corpus']) {
    for (const c of promFixtures[section] as Record<string, any>[]) {
      for (const [strategy, want] of Object.entries(
        c['expected'] as Record<string, string | null>,
      )) {
        const label = `${section}: ${JSON.stringify(c['name'])} ${c['unit']} ${c['instrument']} ${strategy}`;
        it(label, () => {
          const call = (): string =>
            metricName(
              c['name'] as string,
              c['unit'] as string,
              KINDS[c['instrument'] as string] as string,
              strategy,
            );
          if (want === null) {
            expect(call).toThrow(PromNameError);
            expect(call).toThrow('translates to nothing usable');
          } else {
            expect(call()).toBe(want);
          }
        });
      }
    }
  }
});

describe('label names match the reference', () => {
  for (const c of [...promFixtures['label_names'], ...promFixtures['label_corpus']] as Record<
    string,
    any
  >[]) {
    for (const strategy of STRATEGIES) {
      const want = (strategy.startsWith('Underscore') ? c['escaped'] : c['utf8']) as string | null;
      it(`${JSON.stringify(c['attribute'])} ${strategy}`, () => {
        const call = (): string => labelName(c['attribute'] as string, strategy);
        if (want === null) {
          expect(call).toThrow('cannot be a label name');
        } else {
          expect(call()).toBe(want);
        }
      });
    }
  }
});

describe('translator edges', () => {
  it('the fixture sections are not empty', () => {
    expect((promFixtures['translation_corpus'] as unknown[]).length).toBeGreaterThan(100);
    expect(STRATEGIES).toHaveLength(4);
  });

  it('kind constants match the spec', () => {
    expect(new Set(Object.values(KINDS))).toEqual(
      new Set([KIND_MONOTONIC_COUNTER, KIND_NON_MONOTONIC_COUNTER, KIND_GAUGE, KIND_HISTOGRAM]),
    );
  });

  it('rejects an empty attribute', () => {
    expect(() => labelName('', 'NoTranslation')).toThrow('attribute "" cannot be a label name');
  });

  it('names the rejected metric', () => {
    expect(() => metricName('...', '', KIND_GAUGE, 'UnderscoreEscapingWithoutSuffixes')).toThrow(
      'metric name "..." translates to nothing usable',
    );
    const err = (() => {
      try {
        metricName('...', '', KIND_GAUGE, 'UnderscoreEscapingWithoutSuffixes');
      } catch (e) {
        return e as Error;
      }
      return undefined;
    })();
    expect(err?.name).toBe('PromNameError');
  });

  it('an empty name translates to nothing', () => {
    expect(() => metricName('', '', KIND_GAUGE, 'UnderscoreEscapingWithoutSuffixes')).toThrow(
      PromNameError,
    );
  });

  it('only a leading digit is prefixed', () => {
    expect(metricName('a1', '', KIND_GAUGE, 'UnderscoreEscapingWithSuffixes')).toBe('a1');
    expect(metricName('a1', '', KIND_GAUGE, 'UnderscoreEscapingWithoutSuffixes')).toBe('a1');
    expect(labelName('a1', 'UnderscoreEscapingWithSuffixes')).toBe('a1');
  });

  it('an already valid name without suffixes is unchanged', () => {
    expect(metricName('_', '', KIND_GAUGE, 'UnderscoreEscapingWithoutSuffixes')).toBe('_');
  });

  it('a unit that is an Object.prototype key is not read off the prototype', () => {
    expect(metricName('a', 'constructor', KIND_GAUGE, 'UnderscoreEscapingWithSuffixes')).toBe(
      'a_constructor',
    );
    expect(metricName('a', 's/toString', KIND_GAUGE, 'NoUTF8EscapingWithSuffixes')).toBe(
      'a_seconds_per_toString',
    );
  });

  it('annotations and blank units add no suffix', () => {
    expect(metricName('a', '{req}', KIND_GAUGE, 'UnderscoreEscapingWithSuffixes')).toBe('a');
    expect(metricName('a', ' ', KIND_GAUGE, 'UnderscoreEscapingWithSuffixes')).toBe('a');
    expect(metricName('a', 'By/{x}', KIND_GAUGE, 'NoUTF8EscapingWithSuffixes')).toBe('a_bytes');
    expect(metricName('a', 'x}/s', KIND_GAUGE, 'NoUTF8EscapingWithSuffixes')).toBe('a_per_second');
  });

  it('trims a suffix whose delimiter is outside the BMP as one character', () => {
    expect(metricName('a\u{1F600}total', '', KIND_MONOTONIC_COUNTER, 'NoTranslation')).toBe(
      'a\u{1F600}total',
    );
    expect(
      metricName('a\u{1F600}total', '', KIND_MONOTONIC_COUNTER, 'NoUTF8EscapingWithSuffixes'),
    ).toBe('a_total');
  });

  it.each([
    ['UnderscoreEscapingWithSuffixes', true, true],
    ['UnderscoreEscapingWithoutSuffixes', true, false],
    ['NoUTF8EscapingWithSuffixes', false, true],
    ['NoTranslation', false, false],
  ])('strategy flags for %s', (strategy, esc, suffixes) => {
    expect(escapes(strategy)).toBe(esc);
    expect(addsSuffixes(strategy)).toBe(suffixes);
  });
});
