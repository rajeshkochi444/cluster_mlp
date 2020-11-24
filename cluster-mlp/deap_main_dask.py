import random
from ase.optimize import BFGS
from deap import base
from deap import creator
from deap import tools
from fillPool import fillPool
from mutations import homotop,rattle_mut,rotate_mut,twist,tunnel,partialInversion,mate,skin,changeCore
import copy
import ase.db
from ase.calculators.singlepoint import SinglePointCalculator as sp
from utils import write_to_db,checkBonded,checkSimilar
from dask_kubernetes import KubeCluster
from dask.distributed import Client
import dask
import ase
import dask.bag as db
import tempfile

def minimize(clus,calc):
	#clus = individual[0]
	clus.calc = copy.deepcopy(calc)
	with tempfile.TemporaryDirectory() as tmp_dir:
		clus.get_calculator().set(directory=tmp_dir)
	energy = clus.get_potential_energy()
	dyn = BFGS(clus,logfile = None)
	dyn.run(fmax = 0.05,steps = 100)
	energy = clus.get_potential_energy()
	clus.set_calculator(sp(atoms=clus, energy=energy))
	#return energy,
	return clus

def fitness_func1(clus):
    energy = clus.get_potential_energy() 
    return energy, 

def cluster_GA(nPool,eleNames,eleNums,eleRadii,generations,calc,filename,CXPB = 0.5,singleTypeCluster = False):
	best_db = ase.db.connect("{}.db".format(filename))
	creator.create("FitnessMax", base.Fitness, weights=(1.0,))
	creator.create("Individual", list,fitness=creator.FitnessMax)

	toolbox = base.Toolbox()

	toolbox.register("poolfill", fillPool,eleNames,eleNums,eleRadii,calc)

	toolbox.register("individual",tools.initRepeat,creator.Individual,toolbox.poolfill,1)


	#toolbox.register("evaluate1", fitness_func1,calc=calc)
	toolbox.register("evaluate1", fitness_func1)
	toolbox.register("population", tools.initRepeat, list, toolbox.individual)

	#REGISTERING MUTATIONS AND CROSSOVER
	toolbox.register("mate", mate)
	toolbox.register("mutate_homotop", homotop)
	toolbox.register("mutate_rattle", rattle_mut)
	toolbox.register("mutate_rotate", rotate_mut)
	toolbox.register("mutate_twist", twist)
	toolbox.register("mutate_tunnel", tunnel)
	toolbox.register("mutate_partialinv",partialInversion)
	toolbox.register("mutate_skin",skin)
	toolbox.register("mutate_changecore",changeCore)

	toolbox.register("select", tools.selRoulette)
	
	population = toolbox.population(n=nPool)
        
	#Creating a list of cluster atom objects from pouplation
	pop_list = []
	for individual in population:
		pop_list.append(individual[0])

        
	#Dask Parallelization
	def calculate(atoms):
		atoms_min = minimize(atoms,calc)	
		return atoms_min	

	#distribute and run the calculations
	clus_bag = db.from_sequence(pop_list)
	clus_bag_computed = clus_bag.map(calculate)
	lst_clus_min  = clus_bag_computed.compute()
	
	for clus in lst_clus_min:
		print(clus)
		print(clus.get_potential_energy())
		print(clus.get_positions())
	
	population = copy.deepcopy(lst_clus_min)

	fitnesses = list(map(toolbox.evaluate1, population)) #USE DASK TO PARALLELIZE
	#fitnesses = list(map(toolbox.evaluate1, lst_clus_min)) #USE DASK TO PARALLELIZE
	print('fitnesses: ', fitnesses)

	for ind, fit in zip(population, fitnesses):
	        ind.fitness.values = fit
	g = 0
	init_pop_db = ase.db.connect("init_pop_{}.db".format(filename))
	#for cl in population:
		#write_to_db(init_pop_db,cl[0])
	#for cl in population:
		#write_to_db(init_pop_db,cl[0])

	bi = []
	while g < generations:
			mutType = None
			muttype_list = []
			g = g + 1
			print('Generation',g)
			print('Starting Evolution')

			if random.random() < CXPB:
				clusters = toolbox.select(population,2)
				mutType = 'crossover'
				muttype_list.append(mutType)
				parent1 = copy.deepcopy(clusters[0])
				parent2 = copy.deepcopy(clusters[1])
				fit1 = clusters[0].fitness.values
				f1, = fit1
				fit2 = clusters[1].fitness.values
				f2, = fit2
				toolbox.mate(parent1[0],parent2[0],f1,f2)
				child_clus  = parent1[0]	
				child_clus_min = minimize(child_clus,calc)
				new_fitness = fitness_func1(child_clus_min)
				print(new_fitness) #parent1[0], child_clus, child_clus_min are now same objects	
				#print(parent1[0].positions)
				#print(child_clus.positions)
				#print(child_clus_min.positions)

				diff_list = []
				print('checkBonded(parent1[0]: ', checkBonded(parent1[0])) 
				if checkBonded(parent1[0]) == True:
					for c,cluster in enumerate(population):
						diff = checkSimilar(cluster[0],parent1[0])
						diff_list.append(diff)

					if all(diff_list) == True:
						highest_energy_ind = tools.selBest(population,1)[0]
						hei_index = population.index(highest_energy_ind)
						hei_fitness = highest_energy_ind.fitness.values
						if new_fitness < hei_fitness:
							del highest_energy_ind.fitness.values
							population.pop(hei_index)
							highest_energy_ind = parent1
							highest_energy_ind.fitness.values = new_fitness
							population.append(highest_energy_ind)

			else:
				mut_pop = []
				for m,mut in enumerate(population):
					mutant = copy.deepcopy(mut)
					if singleTypeCluster:
						mutType = random.choice(['rattle','rotate','twist','partialinv','tunnel','skin','changecore'])
					else:
						mutType = random.choice(['rattle','rotate','homotop','twist','partialinv','tunnel','skin','changecore'])

					muttype_list.append(mutType)

					if mutType == 'homotop':
						mutant[0] = toolbox.mutate_homotop(mutant[0])
					if mutType == 'rattle':
						mutant[0] = toolbox.mutate_rattle(mutant[0])
					if mutType == 'rotate':
						mutant[0] = toolbox.mutate_rotate(mutant[0])
					if mutType == 'twist':
						mutant[0] = toolbox.mutate_twist(mutant[0])
					if mutType == 'tunnel':
						mutant[0] = toolbox.mutate_tunnel(mutant[0])
					if mutType == 'partialinv':
						mutant[0] = toolbox.mutate_partialinv(mutant[0])
					if mutType == 'skin':
						mutant[0] = toolbox.mutate_skin(mutant[0])
					if mutType == 'changecore':
						mutant[0] = toolbox.mutate_changecore(mutant[0])
					diff_list = []

					if checkBonded(mutant[0]) == True:
						for c,cluster in enumerate(population):
							diff = checkSimilar(cluster[0],mutant[0])
							diff_list.append(diff)

						if all(diff_list) == True:
							mut_pop.append(mutant)
						else:
							pass
				mut_new_lst = []
				for mut in mut_pop:
					mut_new_lst.append(mut[0])
				#fitnesses_mut = list(map(toolbox.evaluate1, mut_pop)) #USE DASK TO PARALLELIZE
				mut_bag = db.from_sequence(mut_new_lst)
				mut_bag_computed = mut_bag.map(calculate)
				mut_new_lst_min = mut_bag_computed.compute()
				
				fitnesses_mut = list(map(toolbox.evaluate1, mut_new_lst_min)) #USE DASK TO PARALLELIZE
				for ind, fit in zip(mut_pop, fitnesses_mut):
					ind.fitness.values = fit
				new_population = copy.deepcopy(population)
				for m1,mut1 in enumerate(mut_pop):
					new_diff_list = []
					if checkBonded(mut1[0]) == True:
						for c2,cluster1 in enumerate(population):
							diff = checkSimilar(cluster1[0],mut1[0])
							new_diff_list.append(diff)
						if all(new_diff_list) == True:
							new_population.append(mut1)
						else:
							pass
				best_n_clus = tools.selWorst(new_population,nPool)
				population = best_n_clus

			print('Mutations were:',muttype_list)
			best_clus = tools.selWorst(population,1)[0]
			print('Lowest energy individual is',best_clus)
			print('Lowest energy is',best_clus.fitness.values)
			bi.append(best_clus[0])
			write_to_db(best_db,best_clus[0])

	final_pop_db = ase.db.connect("final_pop_{}.db".format(filename))
	for clus in population:
		write_to_db(final_pop_db,clus[0])

	return bi,best_clus[0]
