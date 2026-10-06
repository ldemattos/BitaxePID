# checkPID

## Task: Create a new python code to check the tcontrol() behavior

### Requisites:
- Create a new standalone code called checkPID.py;
- It must note modify the existing files;
- The inputs are:
	- Time step, Dt (in s);
	- The PID gains: kp, ki, kd;
	- Initial temperature output,T;
	- Tmax (max simulation time)
	- The deadband;
	- The max, min voltage limits;
	- The input variables must be read from the command line;
- The outputs are:
	- The program must print all the input variables;
	- The program must loop from zero to Tmax, in DeltaT steps;
		- The input variables must be input to tcontrol() function;
		- Every output must be recorded;
		- On the 5th time step a 5% increase must be set to the temperature value;
		- 5 time steps later, do a 2.5% decrease must be set to the temperature value;
		- 5 time steps later, do a 2.5% decrease must be set to the temperature value;
		- 5 time steps later, do a 5% decrease must be set to the temperature value;
		- 5 time steps later, do a 2.5% increase must be set to the temperature value;
		- 5 time steps later, do a 2.5% increase must be set to the temperature value;
		- 5 time steps later, do a 1.6% decrease must be set to the temperature value;
		- 5 time steps later, do a 1.6% increase must be set to the temperature value;
	- There must be saved a plot such as:
		X axis time;
		Y input temp values;
		Y tcontrol() output;
		Y tcontrol() PID output;
		Y ratio PID output / target temperature;
	- The input and output values must be recorded to a csv file;
	- All the new files must be saved on a dir called checkPID;
	- Draw a webpage that show all the output files and auto updates in every run, all plots and data files (csv);
- Program end;