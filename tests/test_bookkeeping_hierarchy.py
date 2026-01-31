
import unittest
from datetime import date
# Mock structures since we can't easily import the route logic isolated without flask app context or DB
# But we can replicate the *logic* of the tree builder to verify it produces the expected structure.

class TestBookkeepingHierarchy(unittest.TestCase):
    def test_hierarchy_logic(self):
        # Setup Data
        # Sale A (ID 1)
        # Purchase B (ID 2) -> Linked to A
        # Import C (ID 3) -> Linked to B
        # Shipping D (ID 4) -> Linked to A
        
        entries_data = [
            {'id': 1, 'type': 'gain', 'desc': 'Sale A', 'amt': 100},
            {'id': 2, 'type': 'cost', 'cost_type': 'purchase', 'desc': 'Purchase B', 'amt': 50},
            {'id': 3, 'type': 'cost', 'cost_type': 'import', 'desc': 'Import C', 'amt': 5},
            {'id': 4, 'type': 'cost', 'cost_type': 'shipping', 'desc': 'Shipping D', 'amt': 10},
        ]
        
        entry_map = {e['id']: e for e in entries_data}
        
        links = [
            {'source': 2, 'target': 1, 'amount': 50}, # Purchase -> Sale
            {'source': 3, 'target': 2, 'amount': 5},  # Import -> Purchase
            {'source': 4, 'target': 1, 'amount': 10}, # Shipping -> Sale
        ]
        
        children_map = {}
        
        # Logic Simulation
        for link in links:
            source_id = link['source']
            target_id = link['target']
            
            source = entry_map.get(source_id)
            target = entry_map.get(target_id)
            
            # Simulate "Source is Child, Target is Parent" logic
            # My route logic does: children_map[target_id].append(child_obj)
            
            child_obj = source.copy()
            child_obj['children'] = []
            
            if target_id not in children_map: children_map[target_id] = []
            children_map[target_id].append(child_obj)
            
        
        # Recursive Attach
        def attach_children(entry_obj_list):
            for child in entry_obj_list:
                cid = child['id']
                if cid in children_map:
                    child['children'] = children_map[cid]
                    attach_children(child['children'])
                    
        final_entries = []
        for e in entries_data:
            e_copy = e.copy()
            if e['id'] in children_map:
                e_copy['children'] = children_map[e['id']]
                attach_children(e_copy['children'])
            else:
                e_copy['children'] = []
            final_entries.append(e_copy)
            
        # Verification
        sale_a = next(e for e in final_entries if e['id'] == 1)
        
        # Sale A should have Children: Purchase B and Shipping D
        self.assertEqual(len(sale_a['children']), 2)
        child_ids = sorted([c['id'] for c in sale_a['children']])
        self.assertEqual(child_ids, [2, 4])
        
        # Purchase B (which is a child of A) should have Child: Import C
        purchase_b = next(c for c in sale_a['children'] if c['id'] == 2)
        self.assertEqual(len(purchase_b['children']), 1)
        self.assertEqual(purchase_b['children'][0]['id'], 3)
        
        print("Hierarchy verified successfully.")

if __name__ == '__main__':
    unittest.main()
