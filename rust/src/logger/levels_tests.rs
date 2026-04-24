use super::*;

#[test]
fn level_order_treats_error_aliases_and_unknown_values_consistently() {
    assert_eq!(level_order("ERROR"), 4);
    assert_eq!(level_order("critical"), 4);
    assert_eq!(level_order("fatal"), 4);
    assert_eq!(level_order("not-a-level"), 2);
}
